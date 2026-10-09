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

## Production source overlay after confirmed UI RED

Mac 2fdf754c RED: 1 PASS / 2 FAIL / 0 ERROR, exit 1. Default first read failed
before reread was reached; explicit mismatch rejection passed; ordinary 503
incorrectly claimed concurrency exhaustion. All 134 original source files and
isolated-copy SHAs matched. The preview task then confirmed this exact R2/R1
source mapping and the original 11-file build/static correspondence.

The source overlay now changes only managerWorkspace.ts and
catalystObservationPanel.ts in production. Default reads adopt validated backend
binding for display without turning it into an explicit query; user-selected
bindings retain exact rejection checks. Selection/announcement defaults remain
separate from explicit intent after reread and manual refresh. Changing or
clearing announcement choice recomputes explicit intent. No query response alias.
The original error status is retained; validated reason_codes allow MODULE_BUSY
to report capacity, MODULE_RESULT_NOT_AVAILABLE to report unpublished results,
and unclassified 503 to report an unconfirmed unavailable service.

The three RED tests are unchanged. The original dailyChannels.runtime.spec.ts
is retained in full except its former guessed-second-request cancellation test
now waits on the default canonical request; cancellation and rejection of the
late response are still asserted. All other runtime cases remain unchanged.
Original dailyChannels.ts, DTO validation and ManagerSelectionView.vue are not
modified. This is a source candidate, not a built/deployed site.

Use an isolated copy of the verified Mac web root already owned by the existing
UI task, not the active source or active dist. In that copy create the marker
and apply the checked overlay (substitute actual absolute paths):

```sh
printf 'v5.ui-candidate.v1\n' > /absolute/isolated-web/.v5-ui-candidate
python3 /absolute/v4/V5/ui/manager-workbench/apply_candidate.py --web-root /absolute/isolated-web
cd /absolute/isolated-web
npm run test -- src/manager-selection/dailyChannels.v5Bindings.spec.ts src/manager-selection/dailyChannels.runtime.spec.ts src/manager-selection/dailyChannels.spec.ts src/manager-selection/catalystObservationPanel.runtime.spec.ts
npm run typecheck
npm run build -- --outDir /absolute/isolated-dist
```

The overlay manifest checks both before/after SHAs and unchanged dependencies;
it accepts the already-added identical RED test and rejects mismatched originals.
Cloud review checked exact source provenance, changed scope, original test count,
manifest SHA and diff. No TypeScript execution, UI test, npm install/build or
preview/static write was performed in the cloud. The same existing Mac task
must report targeted tests, typecheck/build and real date09 default/reread plus
explicit historical date08 UI outcomes. No 10/8 announcement is renamed today.

Separately acknowledged: b26e5616 Mac manager8 PASS, announcement6 PASS, full322
PASS; real new plan dc92c0e960ef4a91b2d9eb52720f232d later CURRENT / consumed=true
with matching identity and unchanged file SHAs, PARTIAL/natural=false. No P2
source changes are made in this UI candidate.

## Follow-up to actual 31e2658c Mac results

Mac: designated suites 48 PASS / 2 FAIL / 1 ERROR, exit 1; the original three
RED tests all passed; typecheck passed. Cancellation still verified abort,
FAILED, cancellation text and suppression of a late response. No build/deploy.

Both assertion failures described the old behavior intentionally removed:
- Original dailyChannels runtime now asserts exactly one GET, exact
  `{date:20261008,view:auto}`, displayed server selection08/publication07/plan08,
  and unchanged legacy URL date06. It no longer requests two invented dates.
- Original catalyst runtime keeps its date-change/abort/late-result assertions
  and now additionally requires the exact fourth argument:
  `{plan_date:20261002,selection_date:20261001,announcement_date:20261002}`.
No tests are removed or skipped. Production panel/API bytes are unchanged from
31e2658c. The overlay accepts the exact prior candidate's runtime-spec SHA as
well as its original baseline when applying this assertion-only follow-up.

### Missing original observation fixture

The preserved catalyst runtime reads FIXTURE_BINDING.json plus
close_recapture.json and close_recapture.candidates.json relative to its source
location: `src/manager-selection/../../../../tests/fixtures/manager_current_observation_20261002`.
Thus an isolated web root resolves the fixture at
`<web-root>/../../tests/fixtures/manager_current_observation_20261002`, not inside
apps/web. The original R1 copy already lacked this fixture: its receipts/p2_delta_receipt.json
line 121 records the same error. This is not established as a copying regression.

Frozen source `8342862:handoff/v4-running-source-20261005/canonical/tests/test_manager_current_observation.py`
contains four authoritative original data SHAs (embedded in the installer):
close_recapture.json, close_recapture.receipt.json,
close_recapture.candidates.json, inputs/close_recapture_pytdx.json.
The referenced raw directory and binding JSON are NOT present in this checkout,
the fixed 8342862 tree, or tracked fixture history available here. The existing
Mac task located the five verified files at
`/Users/lexi/Desktop/学习/v4_app/tests/fixtures/manager_current_observation_20261002`. Do not manufacture binding
JSON, substitute unrelated observation data, skip its test or call it repaired.

`install_observation_fixture.py` accepts the original directory and the binding
SHA separately obtained by the Mac source lookup. The binding SHA is pinned to
`9e5fd49a35fa70aa8d2a85b4b06547fecaae5af9f9248fbffa99e5aa48b28c0c`.
It validates this binding, all four frozen data SHA pins and the two UI-bound hashes,
then copies the exact bytes into the original relative layout and reports the
complete installed manifest. It rejects differing existing files. No fixture
bytes or unverified binding SHA are invented in this candidate.

Mac confirmed the four data files match the binding and original data byte for byte.
These files are untracked; do not claim they exist at the Git candidate. The
historical upstream FIXTURE_BINDING referenced by this local binding is missing,
so its declared `5c8c28ce…` hash cannot be independently checked. The independent
readback exists and matches `3f9639d8…`. The installer copies the five verified
local files unchanged; it does not create an upstream binding or close this
provenance gap. Preserve this limitation in the final Mac report.

Full recheck using the existing Mac fixture (isolated candidate only):

```sh
python3 /absolute/v4/V5/ui/manager-workbench/apply_candidate.py --web-root /absolute/isolated-web
python3 /absolute/v4/V5/ui/manager-workbench/install_observation_fixture.py --source "/Users/lexi/Desktop/学习/v4_app/tests/fixtures/manager_current_observation_20261002" --binding-sha256 9e5fd49a35fa70aa8d2a85b4b06547fecaae5af9f9248fbffa99e5aa48b28c0c --web-root /absolute/isolated-web
cd /absolute/isolated-web
npm run test -- src/manager-selection/dailyChannels.v5Bindings.spec.ts src/manager-selection/dailyChannels.runtime.spec.ts src/manager-selection/dailyChannels.spec.ts src/manager-selection/catalystObservationPanel.runtime.spec.ts
npm run typecheck
```

Cloud checks: Python AST, exact overlay digests, preserved runtime test count,
production-byte equality to 31e2658c and diff check. No cloud tests. The existing Mac task must perform the recheck; the historical upstream binding
provenance gap remains and is not an ignored test error.

### Historical view contract

The panel initializes with `view=auto`; it does not read `view=dynamic` from the
URL. Opening `?date=20261008&view=dynamic` alone therefore does not enable dynamic
mode. After opening the date08 panel, use the “读取口径” select (accessible name
“历史或现在回看”) and choose “现在回看（可能含后续消息）”. Its change handler
sets dynamic and immediately reads the workspace. Verify the actual canonical
GET query has `date=20261008&view=dynamic` (and explicit date bindings only if
the user selected those dates). A default auto response is not evidence that
dynamic mode worked.

The prepared historical plan `2b1f5907eff44341869049532e269709` is reported CURRENT
with 33/54/75 and an actual generation time of 06:02 UTC; it has not been
published. Its use is a present-day look back at October 8, not an as-of historical
plan. Do not backdate generation, relabel October 8 announcement data as today's
data, or claim that this source candidate publishes the prepared plan.
