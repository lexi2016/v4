# US–HK 667 Live Runtime Review Receipt

Checked: 2026-10-15 15:21–15:23 UTC  
Scope: independent, read-only verification of the active 8873 process, release/config binding, live mapping-catalog API, and exact release delta. Browser/UI acceptance was assigned to the parent reviewer and was not repeated here.

## Verdict

`REVIEWED=PASS` · `TESTED=PASS` · `BEHAVIOR_VERIFIED=PASS` · `API_VERIFIED=PASS` for the active r2 runtime API and the requested read behaviors.

The live service is running r2. The API returns the expected default catalog and a `FULL` detail for `R021`, while preserving the research-only safety contract. This verifies the runtime shape and binding; it does not verify the truth of the underlying relationship claims.

## Runtime and release binding

- `launchctl print gui/501/com.lexi.v35.api-only` reported `running`, PID `99039`. The only listener on `127.0.0.1:8873` was PID `99039`.
- The listener executable was `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python`; its working directory matched the active r2 app root: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-mapping-finish-20261015-r2/app`.
- Active LaunchAgent plist SHA-256: `579d18f1d3fa5cde7b26787936fe0e43969a9f826485f55ca39deb8eb910916e` (matches the authorized r2 identity).
- The active manifest path and declared SHA matched `us-hk-mapping-finish-20261015-r2`, SHA-256 `5c6e18640443c65d647e5072ce82472de2f813ef35d245065006ba44a1fe8684`. The active app inventory had 1,213 entries and digest `56a7807a98793b837b61e2c40c7d581ba366115a6e91578869f1dfa966d02845`.
- The loaded plist selected `manager-workbench-v9.json`, SHA-256 `48fd88d8bc8921181a67c059af7907a56c6a78ef20bec480338409e553e60a9d`. Its `relation_root` resolves to the active r2 app root. A recursive comparison against v7 showed `relation_root` as the only changed field.

An independent call to `ops.api_release_integration.verify_api_release_candidate(..., active_pointer="candidate", role="gateway", base_role="gateway")` returned `PASS`. It verified the 10 exact changed paths below and preservation of all 1,203 non-delta entries, with inventory SHA-256 `7cc2c3f9888be451a6f55cffd83fdd82f320728ed6efd8b085e89dce7f0994eb`.

```text
apps/web/dist/assets/managerSelection-aigkxKal.js
apps/web/dist/manager-selection/index.html
apps/web/src/manager-workbench/Workbench.vue
apps/web/src/manager-workbench/api.ts
apps/web/src/manager-workbench/types.ts
apps/web/src/manager-workbench/useWorkbench.ts
v4/manager_workbench/api.py
v4/manager_workbench/research_data/us_hk_667_catalog_20261015.json
v4/manager_workbench/research_data/us_hk_667_review_overlay_20261015.json
v4/manager_workbench/us_mapping_catalog.py
```

## Live API readback

Read-only GETs were made directly to `127.0.0.1:8873`:

- `GET /api/v4/manager-workbench/mapping-catalog` returned HTTP 200, state `STRUCTURE_VALID`, and 611,266 response bytes. The default page reports 667 stocks, with 25 items and 66 relation rows in `SUMMARY` detail.
- Review progress reports 220 source-reviewed relations, 783 unprocessed relations, 0 independently verified relations, and `independent_verification=NOT_RUN`.
- `GET /api/v4/manager-workbench/mapping-catalog?q=R021&offset=0&limit=25` returned HTTP 200 and one matching relation in `FULL` detail (118,225 response bytes). Its source-review status is `SOURCE_REVIEWED`; independent verification remains `NOT_RUN`, and `prediction_eligible=false`. The full response includes the revision/addenda and source-summary sections.
- Both responses carried `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false`. Catalog safety also reports `prediction_validation=UNTESTED` and `historical_PIT=NOT_VALIDATED`.

## Evidence boundary

`STRUCTURE_VALID`, row counts, and `FULL` rendering prove the live API contract and projection behavior. They do not establish that company facts or relationship claims are accurate, independently reviewed, prediction-eligible, PIT-safe, or complete. The live count of independently verified relations remains zero. Natural-period acceptance was not run (`NATURAL_SLOT_UNVERIFIED`). UI verification is outside this receipt and remains with the parent CUA reviewer.

The first activation receipt records a failed bootstrap attempt (`PRECHECK`); the second records `DEPLOYED_API_READBACK_OK`, the active r2 plist SHA, old PID exit, and a two-second settle. This review independently confirmed the currently running listener and current API response. No service, plan, raw data, or producer was changed during this review.
