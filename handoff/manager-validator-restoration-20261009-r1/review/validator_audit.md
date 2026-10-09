# Independent validator restoration audit

Scope: supplied `input/source/managerWorkspace.active-before.ts` and `managerWorkspace.candidate-after.ts` from frozen commit `63e75b7af02866c2d19a484b9561416cb13efd84`, followed by the actual repaired file at `v4/handoff/manager-validator-restoration-20261009-r1/after/apps/web/src/api/managerWorkspace.ts`. This is an isolated frontend source review, not canonical/runtime/API/UI/natural-slot acceptance. Production and original test files were not changed by this reviewer.

## Minimal restoration

| Restored from active-before | Active declaration line | Actual repaired declaration line |
| --- | ---: | --- |
| `IndependentAnnouncementCard` | 126 | 143 |
| `IndependentAnnouncementObservations` | 135 | 152 |
| `ResearchScopeDiagnostics` | 140 | 157 |
| `ResearchInputDiagnostics` | 146 | 163 |
| `ResearchAttention.observation_only` and `.input_diagnostics` | 159 | 176 |
| `observationTime` | 859 | 1076 |
| `validateIndependentObservations` | 899 | 1116 |
| `validateResearchInputDiagnostics` | 930 | 1147 |
| `validateResearchDisplayConsistency` | 955 | 1172 |
| Observation and input validator calls | 1114 and 1115 | 1331 and 1332 |
| Display-consistency call | 1380 | 1633 |

TypeScript AST comparison found all 14 surviving dependencies byte-for-byte identical between supplied before/candidate: `object`, `safe`, `strings`, `records`, `count`, `officialUrl`, `explicitTimestamp`, `sessionDay`, `isJsonObject`, `researchContract`, `researchText`, `researchSha`, `validateFormalSelection`, `validateSelectionDiagnostics`. They need no changes.

## Review of actual repaired source

The actual diff is **+119 / -0**. All four restored interface declarations and all four restored function declarations match active-before exactly. All 86 named declarations already present in candidate-after are unchanged after removing only the two restored optional properties and the three restored call sites for comparison. No unexpected declaration change was found. The final source and the new regression spec have zero TypeScript syntax diagnostics.

Reviewed final-source SHA-256: `2c02d4cff38d749fcad91b892da83029c8269287fbb867a2216f09ef8aa2c43f`. Candidate line references in the following risk discussion refer to the original, unchanged `managerWorkspace.candidate-after.ts`.

## Contract compatibility and concrete risks

1. Keep restored calls bound to the existing `date` argument: it is the workspace/plan target. New `selection_date` and `announcement_date` are separate source/publication bindings. The restored checks do not read `date_bindings`, `daily_channels`, or `market_screen`. The supplied support source `dailyChannels.ts` line 83 binds the plan date separately; line 118 binds each channel's three dates. `connect_selection.py` line 24 and line 74 still derive formal scope from `plan_trade_date`.
2. Keep candidate's `coverage.counts_known === false` branch at line 1459. Restoring the whole baseline workspace validator would remove valid unknown-count screens. No restored check requires those unknown screen counts to become zero.
3. Keep candidate's native-relation `publicationForOrder` at line 1222 and new date/readback functions. Its standing-relation clock exception concerns scored-card evidence; the restored `observation_only` window concerns separate independent observations.
4. Restore `observationTime` verbatim. `researchAwareEpoch` at candidate line 960 is not equivalent: it requires seconds and accepts ISO hour `24:00:00` via `Date.parse`. Baseline observation clocks accept timezone-aware minute-only times and reject hour 24. General timestamp helpers also allow rollover dates that the original observation validator rejects.
5. Preserve `!== undefined` guards: missing historical additions remain readable; present `null`/malformed values must reject. Preserve cross-field witness behavior at active line 973: an existing selection membership is the witness; scope fallback applies when that membership is absent. Do not weaken it to accept a conflicting owner.
6. Original focused specs mostly omit the restored fields. All 13 three-channel cases use `workspaceFixture` without `research_attention`; 11 of 12 daily-automation cases use that fixture plus mapping/plan fields. The actual reader-failure case is the exception. Passing those 25 tests alone does not establish coexistence.
7. Issue8's renderer dependency must be the matching original active renderer for all compared variants. A later renderer that lacks observation/diagnostic DOM creates unrelated baseline failures; it is test support, not a second production edit.

## Independent evidence

An in-memory-only TypeScript transpilation restored the exact missing baseline bodies/types/calls in the candidate and ran eight coexistence probes. Result: **8 passed, 0 failed**, all payloads unchanged, zero source files written by that probe. The envelope combined the original Issue8 observation/input fixture with different plan, selection and announcement dates, daily-channel fixtures, and a `CANNOT_CONFIRM` unknown-count screen.

| Probe | Result / expected error |
| --- | --- |
| Valid combined envelope | Accepted, same object, unchanged |
| Observation `orders_sent: true` | `WORKSPACE_SAFETY_INVALID` |
| Incomplete US input claiming assessed-zero | `WORKSPACE_US_INPUT_COMPLETENESS_INVALID` |
| Different scope calendar SHA | `WORKSPACE_RESEARCH_DISPLAY_CALENDAR_BINDING_INVALID` |
| Unknown screen claiming selected count zero | `WORKSPACE_SCREEN_COUNT_INVALID` |
| Announcement date different from request | `WORKSPACE_DAILY_DATE_BINDING_MISMATCH` |
| Valid timezone-aware minute-only clock | Accepted, same object, unchanged |
| Hour-24 observation clock | `WORKSPACE_OBSERVATION_TIME_INVALID` |

The probes are now saved as the new `review/managerWorkspace.validatorRestoration.spec.ts`, with imports intended for placement under `apps/web/src/api`. Main agent will execute the exact file against candidate-before and the final source. This reviewer has not run that final-source Vitest gate: **NOT_RUN**. The in-memory probe is not a deployment or integration claim. Original 76/25 tests remain unchanged.

No direct conflict between verbatim validator restoration and retained new contracts was found. Live services, GitHub writes, source producers, market data, trading/BUY behavior, and service state were not accessed or changed by this reviewer.
