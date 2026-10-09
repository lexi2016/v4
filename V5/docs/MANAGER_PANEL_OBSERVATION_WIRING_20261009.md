# Manager current panel observation: optional read + existing UI

Integration base: `3837c476e2921d70fdb54e343a595363cd4eb86d`.
Four original owner files copied byte-for-byte from `2edcc42204f6e319da9df8cad7578d9f6eaf13b3`: rebound_observation.py, its capsule, original tests and original handoff document. All capsule bindings statically match. No owner algorithm edits or business recomputation.

Parent reports Mac owner 13/13 PASS (15 differential variants), real 695 rows all INCOMPLETE_INPUT, missing 10/5–10/7, observed 2026-10-09 20:53:19 HKT on 10/8 panel. These are upstream reported results, NOT cloud execution or integrated UI acceptance.

Optional manager request:
```json
{"rebound_observation":{"root":"<resolved absolute original observation output root>","reference":{"run_id":"<32 hex>","artifact_sha256":"<64 hex>","manifest_sha256":"<64 hex>","receipt_sha256":"<64 hex>"}}}
```
Use the existing Mac `manager-binding.json` values; do not guess or regenerate them. Cloud has not read that Mac file. All input/output/other-owner roots must remain distinct. Fixed reader verifies marker, three raw SHAs, run/manifest/receipt/source/row contracts and source capsule. Reader runs before and after workspace work; no collector or calculator is invoked. Missing/damaged products become optional observation gaps and do not replace other workspace lanes. Bad request identity/root overlap rejects the request.

Original manager_observation date/cutoff/synthetic gates remain. Use an actual later request time with the matching target/signal date to view the current observation. Old saved-plan cutoff is never rewritten: if it predates finished_at, no rows are admitted. Refresh keeps the original same-run plan readback; observation is appended afterward and never saved into the plan. It cannot populate market_screen, strict/near, selection counts or BUY. Do not enable registry_observation for this integration.

The API field is `rebound_panel_observation`. To keep the 300000 lexical budget fixed, it contains a **summary of every admitted row**, not a second copy of the complete row array. `row_summary` includes exact total/incomplete/complete counts, two separate true/false/unknown count sets, unions of missing and duplicate historical dates and input gaps, and canonical SHA of all original rows. Full row detail stays in the immutable original artifact referenced by three SHAs; no input or source artifact is truncated. `row_summary=null` means unavailable/rejected, never zero. Manager transport/frontend are summary-only this increment; no new full-row endpoint is claimed.

Existing observation page gains a small optional section alongside the strategy section: input date, target, real observed_at, record count explicitly not candidates, missing dates, comparison unknown counts, formal CANNOT_CONFIRM, units/history scale/finality/eligibility unknown, expandable source reference and aggregate gaps. Empty binding hides the section; rejected binding displays a gap and unknown count. Uses existing styling/textContent. Original formal screen remains unchanged.

Cloud static validation only: Python AST, original/capsule/overlay SHA, diff whitespace. No product tests, typecheck/build, real-input reads, publishing or deployment performed.

Mac tests on fixed integration commit:
```bash
PYTHONPATH=V5/src:V5/tests python3 -m unittest test_manager_panel_observation.ManagerPanelObservationTests test_manager_rebound_observation.ManagerReboundObservationTests test_manager_response_budget.ManagerResponseBudgetTests -v
```
New backend: eight cases covering saved pure read/no formal changes; missing/tampered product; date/cutoff; synthetic exclusion; refresh save exclusion; overlap/SHA; 695-row summary combined with a >252000 lexical-node workspace fixture under the existing budget. No new owner calculation is needed for these wiring tests.

Apply existing isolated UI overlay (never V4), then:
```bash
python3 V5/ui/manager-workbench/apply_candidate.py --web-root "$ISOLATED_WEB_ROOT"
```
From the isolated web root:
```bash
npm run test -- src/manager-selection/reboundPanelObservation.spec.ts src/manager-selection/catalystObservationPanel.runtime.spec.ts src/manager-selection/catalystViewNavigation.spec.ts src/manager-selection/dailyChannels.v5Bindings.spec.ts
npm run typecheck
npm run build -- --outDir "$ISOLATED_DIST_ROOT"
```
Four renderer tests plus one actual existing-panel mount test. Real manager/API/UI acceptance remains Mac work; verify existing saved binding, row_summary=695/incomplete=695, both unknown=695, exact dates/timestamp, unchanged formal counts and response byte/node budget before any independently authorized preview action. Full combined suite counts must not be added to old baselines.
