# Bounded manager display cleanup

Baseline c7a3686e9794c71b7fb257a17449c5f500f2783f; same authorized V5 branch.
User-approved design: first screen contains plan/data dates, the three strategy
states, and current stock research results. US matches group by HK stock (multiple
US clues retained on one card), with relation type, reason, named source links,
and explicit assessed versus unassessed scope. No fixed live counts or stocks.
Announcement and rebound each have one expandable summary; unavailable is not zero.
Original materials, controls, duplicate legacy lanes, raw reasons and audit identity
remain inside labelled closed details. HK_CONNECT is never relabelled US mapping.
Use the existing V4 DOM/styles, responsive wrapping and Asia/Shanghai timestamps.

Affected source: catalystObservationPanel.ts layout/lifecycle, usMappingCoverage.ts
read-only rendering, new managerStrategySummary.ts for payload-based summaries;
matching candidate tests and overlay manifest. Existing renderers, algorithms,
API contracts, source dates and frozen backend issues remain unchanged. No new
requests or automatic actions. Legacy limited issuer capture remains available
only under original advanced details, not the normal strategy entry.

Cloud verification is static only. Mac E must run candidate UI tests/typecheck
and inspect desktop/mobile browser layout, expandability, safe source links,
missing/zero/partial results, failure and date-switch clearing before publishing.
This candidate does not resolve announcement HTTP 503/404 or missing source data.

Implemented: grouped cards are derived only from the current daily_run.matches
when scope diagnostics and daily run state permit display. Historical seed cards
are not promoted. Official source titles are clickable; unsafe schemes are not
links, with original bytes still available inside evidence. Scope details and
legacy UI remain closed by default. Valid empty has its own wording; an unavailable
result never becomes zero. Independent analysis service failure is stated on the
announcement summary and does not rewrite the channel result. Header time display
converts offset-bearing timestamps to Beijing time; timezone-free input is unknown.

Candidate tests: existing 8 scope cases preserved; 2 added grouped-card/empty-state
cases; 2 new channel/time cases; the existing page-wiring test now asserts default
folding and access to original details. The previous daily-channel test's explicit
unfolded-layout assertion is updated to the new closed original-details contract;
all source/date/stock/reason assertions are retained.

Mac E commands (only isolated verified copy, existing marker and fixture):

```sh
python3 /absolute/v4/V5/ui/manager-workbench/apply_candidate.py --web-root /absolute/isolated-web
cd /absolute/isolated-web
npm run test -- src/manager-selection/managerStrategySummary.spec.ts src/manager-selection/usMappingCoverage.spec.ts src/manager-selection/catalystObservationPanel.runtime.spec.ts src/manager-selection/dailyChannels.runtime.spec.ts src/manager-selection/catalystViewNavigation.spec.ts
npm run typecheck
```

Browser acceptance: real payload renders the actual HK card count, with multiple
US clues grouped by HK symbol; no hardcoded 3/4/19. Verify narrow and wide viewport
source links do not overflow, the first screen has no raw run/SHA/reason strings,
announcement/oversold each have one closed summary, and all original evidence and
limited-capture controls remain accessible under details. Confirm failed reads,
manual date changes and browser navigation do not retain stale cards. No cloud
product tests/build/browser/owner runs or deployment were performed (NOT_RUN).

## Mac failure and minimal follow-up

E reported baseline `9a30826fb702f56d010ddab7ca6d8230fdda58c7`:
28 PASS / 34 FAIL; typecheck FAIL; build PASS; not deployed. Desktop/mobile
headless render lacked strategy/stock cards. Root cause: local summary DOM variable
`strategySummary` shadowed the imported formatter; initialization called an element
as a function. Rename only this DOM binding and all its references to
`reboundStrategySummaryNode`. Formatter calls and business behavior stay unchanged.
The scoped details selector inferred Element; both test details queries now use
`querySelector<HTMLDetailsElement>` before reading `.open`. No assertions removed,
weakened or skipped. Existing failing mount cases remain the regression coverage.

Cloud static verification: import-versus-local declaration text scan across overlay
TypeScript found no further overlaps; manifest digests and diff whitespace match.
This scan is not a compiler. TypeScript/parser packages are unavailable locally;
none installed. Product tests, typecheck, build and visual verification remain
NOT_RUN here. E must repeat all commands above, its build and desktop/mobile checks.

Known unrelated source/service limits retained: announcement selection 404
ROUTE_NOT_CONFIGURED; target 20261012 analysis 503 MODULE_RESULT_NOT_AVAILABLE;
target 20261009 analysis 200 (E observations). These are not zero-result claims.
Old page had many empty-result blocks, not empty-string titles; old general US
material scope and daily reviewed relation scope are different. This follow-up
only fixes rendering initialization and test typing; no service or algorithm edits.

## Refresh test selector follow-up

E reported `1f3e218265646ab2f6b8e47c01c6357fac8c3e8b`: 61 PASS / 1 FAIL;
typecheck/build and headless desktop/mobile/navigation PASS; not published.
The remaining refresh test selected `button:nth-of-type(2)`, which now refers to
cancel after the layout change. The test now opens the named plan-actions details,
uses its scoped accessible button name, and waits until that button is enabled.
The original single-refresh and no-second-GET assertions remain unchanged. No
product source changes. Text scan found no other indexed button selector in this
overlay's source/tests; other button queries already select names or data attributes.
Cloud verification remains manifest hashes/diff only; no product test run. E should
repeat the same complete test/type/build and visual acceptance before publication.

## Testing Library option correction

E reported `55377ed7ac2993337f2cb892cc717732c5419f84`: 62/62 PASS and build PASS,
but typecheck TS2769 at the getByRole options. Remove only `exact: true`; keep the
string name, scoped details lookup, enabled wait and all refresh/result assertions.

API verification before this edit: both available checked-in web package-lock.json
files (v4-running-source-20261005/canonical and hk-close-daily-20261007/candidate)
pin @testing-library/vue 8.1.0 and @testing-library/dom 9.3.4. No installed local
Testing Library declarations were found. Read the lock-resolved registry archives
in memory and verified their sha512 integrity against the locks; no install or
package execution. Vue types/index.d.ts re-exports DOM queries; DOM types/queries.d.ts
ByRoleOptions supports name but not exact. dist/queries/role.js passes the accessible
name to matches; dist/matches.js compares a string matcher by strict equality.
Thus the string name retains exact accessible-name matching without that option.
This verifies the available locked API, not an independent inspection of Mac's
node_modules; E's TS2769 agrees with the checked types.

Cloud: one-option diff and manifest hashes checked; product tests/type/build NOT_RUN.
E previously verified 86 product source/11 build files equal 1f3e2182; no product
bytes change in this correction. Prior visual evidence may be reused per E, but
publication remains pending successful typecheck and E's final acceptance.
