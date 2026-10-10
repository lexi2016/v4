# US coverage UI candidate — cloud source only

Baseline: `8a667188d75701fc44580b470f83cc264a304f7c` on
`v5/module-isolation-20261008`. Source root: this directory's `source/apps/web`.
This patch consumes the existing manager workspace payload at
`us_mapping_research.coverage_diagnostics`, immediately below the existing research
attention section using its existing heading/paragraph styles. It adds no API,
producer, selection rule, refresh operation or deployment.

The display uses returned scope, reviewed keys/count, session, configured sample,
rising/assessed/unassessed counts and original reason codes. The current four-key
registry remains limited scope; no sample counts or key count are hardcoded.
Nonnegative integer zero remains 0. Null, absent/invalid counts, unavailable state
and incompatible diagnostics remain unknown. Full-market/formal/natural promotions
are not accepted by this display. Target qualification remains CANNOT_CONFIRM.
`RESEARCH_SAVED_NOT_FORMAL_SELECTION` is an explanation of the research-only
boundary, not a newly inferred save result; the text directs users to the original
plan readback status for save success. Clearing the workspace also clears this
section, including failed reads after date changes.

Candidates: eight renderer cases (including four parameterized contract cases)
and one manager mount/date-failure wiring case. Synthetic counts intentionally
differ from the pending real-batch evidence. Existing tests are preserved.
Cloud: manifest SHA checks and git diff whitespace only. UI tests/typecheck/build,
Mac acceptance, preview publication and natural execution: NOT_RUN here.
The 46081f5 problem package and all frozen backend repairs are preserved.

Existing Mac E task only, on its isolated verified source copy (substitute paths):

```sh
python3 /absolute/v4/V5/ui/manager-workbench/apply_candidate.py --web-root /absolute/isolated-web
cd /absolute/isolated-web
npm run test -- src/manager-selection/usMappingCoverage.spec.ts src/manager-selection/catalystObservationPanel.runtime.spec.ts src/manager-selection/catalystViewNavigation.spec.ts
npm run typecheck
```

The isolated copy must retain the already established original observation fixture
and `.v5-ui-candidate` marker described in NEXT.md. Overlay manifest records original,
previous-candidate and new file SHAs, accepting the current baseline or original
bytes; never apply to V4 or the live preview. E owns further preview validation
and publication. F owns verification of the real US counts; this patch asserts none.
