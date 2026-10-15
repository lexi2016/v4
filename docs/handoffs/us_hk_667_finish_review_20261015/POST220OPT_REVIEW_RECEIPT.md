# Independent post-220 catalog optimization review

Verdict: `REVIEWED=PASS`; `TESTED=PASS`; `BEHAVIOR_VERIFIED=PASS` for the frozen catalog candidate, its in-process FastAPI route, and the Vue component behavior covered here. P0/P1/P2 findings: none within this scope.

Reviewer: independent task identity `mapping_220_final_review`, Luna Max. Review date: 2026-10-15. This review is limited to the supplied post-220 optimization candidate. It does not claim active-release integration, deployment, live API or rendered-browser acceptance, or natural-slot verification.

## Frozen inputs and data boundary

- Reviewed `post220opt/sourcebase_delta.diff` against its frozen preimage and checked the separate `delta_from_catalog40.diff` for the active 40-to-220 integration base. Both contain the same six catalog/component/test paths listed in `owned_changed_paths.json`; no pool, engine, BUY, or service changes are included.
- All nine frozen preimage hashes and all nine postimage hashes match their manifests. The source overlay remains SHA256 `72a0f074e6412036cd103c7f73ccf15230eb3d1633c09742c88653b863eba384`. The supplied batch11 ZIP is present and its SHA256 matches `8a214c3c10931e2ab807a3f1701449105702c68186a07a3c1da717413e69fab1`.
- Independent Python coverage verifies the builder reproduces the overlay, all 220 exact-RID responses equal their complete source revisions, original 667 stock and 1,003 relation records are conserved, and progress is 220 relations / 92 stocks / 89 fully recorded stocks / 783 unprocessed relations. Independent verification remains 0 / `NOT_RUN`; source fact status stays `PENDING`, prediction eligibility stays false, prediction stays `UNTESTED`, and historical PIT stays `NOT_VALIDATED`.
- Compared all 40 prior records to `prior40_change_log.json`: 240 revision-field changes and 3,210 evidence-field changes match their logged before/after values. The R021 jurisdiction addendum `B5L3-SHARED-H-JURISDICTION-20261015` is retained for R021 and R073; both remain `OPEN`. The original fact state, current-applicability state, and field assessments remain unchanged, as also asserted by the focused test.
- Reused the existing `BATCH220_SEMANTIC_SPOTCHECK.md` for substantive-source boundaries as instructed. It records 0 full independent fact acceptances and preserves the R137 wording ambiguity and R021/R073 identity-metadata conflict. The UI labels current usage limits as “使用限制 / 禁止据此推断”; this is a source-display boundary, not a factual resolution.

## API and UI behavior

- Default list rows expose the bounded summary and addenda; evidence, full research records, and field assessments are returned only for exact-RID detail. The reproduced default FastAPI response is exactly 611,266 bytes for 667 matching stocks, down from 4,784,175 bytes in the frozen pre-optimization comparison. The eight-call warm mean was 9.11 ms versus 59.93 ms in this run. These are in-process TestClient measurements with FastAPI serialization, not live service or browser latency.
- RID detail returns the complete revision for the requested relation and preserves the same catalog/revision identity and safety flags. The component validates RID, HK/US/source-row identity, SHA values, and research-only flags before displaying it.
- The component test covers lazy detail loading, visible 503 failure and retry, discarding a late response after pagination, rejecting a wrong RID, rendering full evidence after a valid response, and allowing only safe HTTP/HTTPS source URLs. This is mocked-transport component behavior, not browser/runtime acceptance.

## Independent checks

- `PYTHONPATH=. .venv/bin/pytest --basetemp=/tmp/us_hk_finish220opt_reviewer_20261015 -q tests/manager_workbench/test_us_mapping_catalog.py`: **12 passed**; one existing Starlette/httpx deprecation warning.
- From `apps/web`, `node_modules/.bin/vitest run src/manager-workbench/__tests__/us_mapping_catalog.spec.ts`: **1 passed**.
- From `apps/web`, the specified `vue-tsc --noEmit --strict ... Workbench.vue useWorkbench.ts` command: **exit 0**.
- Re-ran `post220opt/measure_api.py`; default payload size reproduced exactly at **611,266 bytes**. No files were written by the measurement script.

## Exclusions

The parallel `v4/manager_workbench/api.py` HK-history change is recorded in `post220opt/concurrent_changes.json`, its observed SHA matches the postimage manifest, and it is excluded from both catalog deltas and this review. It was not reviewed or modified here. No live service, release pointer, deployment, or external source was touched. Independent company-fact verification, prediction/backtest/PIT acceptance, old-997 comparison, API/UI runtime binding, and natural-slot results remain `NOT_RUN` / `CANNOT_CONFIRM`.
