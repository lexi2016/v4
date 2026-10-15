# Live independent review

Reviewer: `mapping700_review` (independent from `mapping700_writer`)
Candidate manifest SHA256: `f80879b7802ad683a734c64d011896031611bb0a9c249184b6feb54ca8c0ea80`

REVIEWED=PASS — the current listener, active plist/config/manifest, live API responses, and served static assets match the R2 candidate.
BEHAVIOR_VERIFIED=PASS — live aggregate counts, exact R001/R700 behavior, research-only flags, and candidate-bound static resource hashes passed readback.

## Runtime identity

- Independently read `LIVE_DEPLOYMENT_RECEIPT.md/json`, `runtime-activation-receipt-r2.json`, and `RUNTIME_INDEPENDENT_REVIEW_R2.md`. The R2 activation receipt reports `ACTIVATED_API_READBACK_OK`; its SHA256 `3af07836db36e07d70f3430d7fe6479e1cc63c6a29a7a81064d580e7538ec1b8` matches the deployment receipt. The recorded relative activation-receipt path resolves to that R2 receipt.
- Current `lsof` readback shows PID `30387` (`python3.14`) listening on `127.0.0.1:8873`. `ps` confirms the `apps.api.v35_api.run` module, host, port, and expected v3.5 virtualenv interpreter; `lsof` confirms cwd `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-mapping700-20261016-r2/app`.
- The active plist SHA256 is `578c5bed8e6465a1f7b2b409c88a8ec2dcf7358efb3ea111cd31e077310aa5d8`. Its working directory, release ID, app root, manifest path/SHA, port, and `V4_MANAGER_WORKBENCH_CONFIG_PATH` point to R2. The release manifest SHA256 is `f80879b7802ad683a734c64d011896031611bb0a9c249184b6feb54ca8c0ea80`; the configured R2 JSON SHA256 is `7a6d9689df73f832e15efd53923ab69d03ebc4f0357635bb8d9e67d6342e35b5`.

## Live API and static readback

- `GET /api/v4/manager-workbench/mapping-catalog` returned HTTP 200, 619,286 bytes, SHA256 `ee1805b1b28bbf14fe79918c7f9454bb8f73958451eb9e6f34b6e51a86bd4450`: 667 members, 1,003 relations, 700 source-reviewed, 303 unprocessed, and 0 independently verified. Safety flags are `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false`.
- Exact `R001` GET returned HTTP 200 as `SOURCE_REVIEWED` / `FULL`; its evidence includes both `declared_unresolved_navigation_reference_json` and `evidence_wording_clarifications_json` on the same row. Exact `R700` GET returned HTTP 200 as `NOT_PROCESSED` / `SUMMARY` / `review_revision=null`.
- `GET /manager-selection/` returned HTTP 200. Served entry SHA256 `8a2d47ea8616e5b7f658bd150947bad7674cf9153ab559e8f33a297ff8d68a9e` matches both the R2 candidate file and its manifest entry. The referenced `/assets/managerSelection-CnQlnjWW.js` returned HTTP 200; served SHA256 `002f4dbd045590dd13331a231de453d5d2e39c6f1282a2097af38f7f397fba59` matches the R2 candidate file and manifest entry.

No P0/P1/P2 mismatch was found in this frozen live identity/API/static scope. The controller's rendered UI check is recorded separately in `UI_REVIEW.md` and was not repeated here. `CANNOT_CONFIRM`: natural-time behavior, independent semantic fact acceptance (current count is 0), prediction validation, and historical PIT validation. This review performed read-only process/file checks and HTTP GETs; it did not start or stop a service or run a plan.
