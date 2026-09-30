# Issue #8 R3 execution contract

Input baseline: `cf306997359dfadedb162033554c092d740eca33`.
PR #9 remains Draft. Issue #8 remains Open. No merge/deploy authorization.

## R3-A — target-date HK Connect authority supply

**GOAL**
Extend the existing 17:20 owner `v35_dispatcher.research_panel_daily_hk` so the SAME existing Futu plate calls retain immutable per-plate membership/provenance and publish the already-approved `HK_CONNECT_FULL_MARKET` authority contract through the existing publication flow.

**WRITER**
Exactly one Luna Max Writer, after preflight PASS.

**REVIEWER**
Independent Luna Max Reviewer. Must not be the Writer.

**ALLOWED_PATHS**
Only canonical V4 source paths proven by `SOURCE_RELEASE_BINDING_RECEIPT.json` to map to the configured owner/release, plus dedicated R3-A tests/fixtures/receipts and existing authority publication code that the proven source graph already owns.

**FORBIDDEN_PATHS**
Configured release snapshot; disabled Stage full-market producer; Vibe 8910; A-share Stage; BUY/order gates; parallel producer; second Futu request; hard-coded membership; ordinary HK security master as eligibility authority; old-date authority; R1/R2 files except read-only regression inputs.

**PASS_SIGNAL**
1. Canonical-to-release binding preflight PASS.
2. Deterministic tests show each existing `get_plate_stock` result is recorded before normalization/dedup with plate id, request_start_at, acquired_at/request_finished_at, target_date, capture_run_id, raw row count, canonical serialization rule and SHA.
3. Partial plate failure is fail-closed; union membership is never reduced by quote validity filtering.
4. Published authority satisfies the original R2 reader schema/identity/date/source/time contract.
5. Independent Reviewer PASS.
6. Authorized real owner canary yields owner receipt, immutable per-plate capture, manifest/run_id/SHA and original-reader acceptance with set equality.

**STOP_RULE**
STOP before production-code modification if canonical V4 -> configured release ownership cannot be proven. STOP before real provider execution if activation/source binding is not approved. STOP if one plate fails. STOP if authority timing is later than the consumer cutoff required by the target selection; preserve CANNOT_CONFIRM rather than backdating.

## R3-B — stale saved-plan binding diagnostic

**GOAL**
Fix the P2 where changing only the HK Connect owner-code pin can leave a saved workspace marked CURRENT while `selection_diagnostics` still exposes the previous owner SHA.

**WRITER**
Same single Writer or a sequential handoff after R3-A files are frozen. Never concurrent edits to the same file.

**REVIEWER**
Independent Luna Max Reviewer.

**ALLOWED_PATHS**
Only the frozen R1+R2 manager workspace/connect-selection identity/readback paths necessary for the changed-pin case, plus R3-B tests/receipts.

**FORBIDDEN_PATHS**
R3-A collector/publication files; Stage/BUY/Vibe; unrelated plan semantics; announcement classification.

**PASS_SIGNAL**
1. Changed owner pin with same date/membership/artifact cannot return stale binding diagnostics.
2. Binding-unchanged saved-plan reuse remains normal.
3. No pool widening or BUY effect.
4. R2 27/27 and affected R1 47/47 remain green.
5. Independent Reviewer PASS.

**STOP_RULE**
No broad workspace refactor. If the minimal identity/readback change requires unrelated plan semantics, stop and return design evidence.

## Evidence state labels
Every delivery must separately state: IMPLEMENTED, TESTED, REVIEWED, BEHAVIOR_VERIFIED, DEPLOYED, API_VERIFIED, UI_VERIFIED, NATURAL_VERIFIED. Missing evidence = CANNOT_CONFIRM.
