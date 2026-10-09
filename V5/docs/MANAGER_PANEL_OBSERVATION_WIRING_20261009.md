# Manager current panel observation: optional read + existing UI

Integration base: `3837c476e2921d70fdb54e343a595363cd4eb86d`.
Four original owner files copied byte-for-byte from `2edcc42204f6e319da9df8cad7578d9f6eaf13b3`: rebound_observation.py, its capsule, original tests and original handoff document. All capsule bindings statically match. No owner algorithm edits or business recomputation.

Parent reports Mac owner 13/13 PASS (15 differential variants), real 695 rows all INCOMPLETE_INPUT, missing 10/5–10/7, observed 2026-10-09 20:53:19 HKT on 10/8 panel. These are upstream reported results, NOT cloud execution or integrated UI acceptance.

Optional manager request:
```json
{"rebound_observation":{"root":"<resolved absolute original observation output root>","reference":{"run_id":"<32 hex>","artifact_sha256":"<64 hex>","manifest_sha256":"<64 hex>","receipt_sha256":"<64 hex>"}}}
```
Use the existing Mac `manager-binding.json` values; do not guess or regenerate them. Cloud has not read that Mac file. All input/output/other-owner roots must remain distinct. Fixed reader verifies marker, three raw SHAs, run/manifest/receipt/source/row contracts and source capsule. Reader runs before and after workspace work; no collector or calculator is invoked. Missing/damaged products become optional observation gaps and do not replace other workspace lanes. Bad request identity/root overlap rejects the request.

Original manager_observation date/synthetic/future-data gates remain. Independent current observations are checked against datetime.now(timezone.utc) captured inside the server read projection, never against caller now or a saved-plan cutoff. The response labels observation_read_as_of separately from the unchanged plan_research_cutoff and observed_at. Explicit historical view or target date other than actual current Hong Kong date suppresses current rows. Today’s saved plan may show this separately labelled current observation; it is not evidence available to the plan at its original cutoff. Refresh keeps the original same-run plan readback; observation is appended afterward and never saved into the plan. It cannot populate market_screen, strict/near, selection counts or BUY. Do not enable registry_observation for this integration.

The API field is `rebound_panel_observation`. To keep the 300000 lexical budget fixed, it contains a **summary of every admitted row**, not a second copy of the complete row array. `row_summary` includes exact total/incomplete/complete counts, two separate true/false/unknown count sets, unions of missing and duplicate historical dates and input gaps, and canonical SHA of all original rows. Full row detail stays in the immutable original artifact referenced by three SHAs; no input or source artifact is truncated. `row_summary=null` means unavailable/rejected, never zero. Manager transport/frontend are summary-only this increment; no new full-row endpoint is claimed.

Existing observation page gains a small optional section alongside the strategy section: input date, target, real observed_at, record count explicitly not candidates, missing dates, comparison unknown counts, formal CANNOT_CONFIRM, units/history scale/finality/eligibility unknown, expandable source reference and aggregate gaps. Empty binding hides the section; rejected binding displays a gap and unknown count. Uses existing styling/textContent. Original formal screen remains unchanged.

Cloud static validation only: Python AST, original/capsule/overlay SHA, diff whitespace. No product tests, typecheck/build, real-input reads, publishing or deployment performed.

Mac tests on fixed integration commit:
```bash
PYTHONPATH=V5/src:V5/tests python3 -m unittest test_manager_panel_observation.ManagerPanelObservationTests test_manager_rebound_observation.ManagerReboundObservationTests test_manager_response_budget.ManagerResponseBudgetTests -v
```
New backend: eleven cases (including the current-read clock correction below) covering saved pure read/no formal changes; missing/tampered product; date/cutoff; synthetic exclusion; refresh save exclusion; overlap/SHA; 695-row summary combined with a >252000 lexical-node workspace fixture under the existing budget. No new owner calculation is needed for these wiring tests.

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


## Current-read clock correction and existing UI fixture dependency

Mac reported integration 8b610b29: backend 41/41 PASS including eight new wiring cases; UI 33 PASS / 1 FAIL due to missing original fixture, typecheck/build NOT_RUN. The real binding was rejected because the saved plan cutoff 18:15:54 preceded the 20:53:20 completion. This increment changes only the independent observation validation clock, preserving saved plan and original artifact bytes, PIT fields and selection logic. Added fixed 18:15 plan / 20:53 observation / 21:06 server read case, future-observation rejection, explicit historical-view suppression, and caller-now non-authority check. No clock parameter is exposed on requests. Existing original owner reader/projector bytes stay pinned.

The preserved runtime suite requires the original verified fixture at `<isolated-web-root>/../../tests/fixtures/manager_current_observation_20261002`, determined by the test’s import.meta.url, not `<isolated-web-root>/tests`. This is an existing dependency described in NEXT.md, not newly fabricated input. Mac should locate its already verified source; the previously documented original location is `/Users/lexi/Desktop/学习/v4_app/tests/fixtures/manager_current_observation_20261002` (cloud has NOT checked this path). Install only if its frozen bytes match:

```bash
python3 V5/ui/manager-workbench/install_observation_fixture.py \
  --source "$EXISTING_VERIFIED_FIXTURE_DIRECTORY" \
  --binding-sha256 9e5fd49a35fa70aa8d2a85b4b06547fecaae5af9f9248fbffa99e5aa48b28c0c \
  --web-root "$ISOLATED_WEB_ROOT"
```

The installer checks the marker, original binding plus four fixed raw-file SHAs and copies byte-identically. Do not generate a new binding, skip the test, overwrite differing evidence or claim fixture acceptance if the source cannot be located. Then rerun the fixed candidate suite/typecheck/build from the existing handoff. This cloud increment runs only AST/hash/diff checks.
