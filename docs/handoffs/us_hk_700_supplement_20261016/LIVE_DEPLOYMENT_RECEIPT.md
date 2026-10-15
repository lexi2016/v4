# Local research deployment receipt

**Status: DEPLOYED / API_VERIFIED by deployment writer.** The candidate and activation path have independent R2 runtime review PASS. The controller owns rendered UI verification. No natural-slot or semantic fact acceptance is claimed.

Active release: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-mapping700-20261016-r2` (manifest SHA256 `f80879b7802ad683a734c64d011896031611bb0a9c249184b6feb54ca8c0ea80`).

- PID `30387` is listening on 127.0.0.1:8873; launchd state is `running`. The process command is `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python -B -m apps.api.v35_api.run --host 127.0.0.1 --port 8873 --stage-selection-root /Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection`.
- Process cwd: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-mapping700-20261016-r2/app`; lsof confirms the same cwd. Python interpreter image: `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/python/cpython-3.14.6-macos-aarch64-none/bin/python3.14`.
- Active API plist SHA256 `578c5bed8e6465a1f7b2b409c88a8ec2dcf7358efb3ea111cd31e077310aa5d8`. Config `/Users/lexi/Library/Application Support/com.lexi.v4.local/config/us-hk-mapping700-20261016-r2.json` SHA256 `7a6d9689df73f832e15efd53923ab69d03ebc4f0357635bb8d9e67d6342e35b5`.
- Runtime release-manifest environment SHA256 `f80879b7802ad683a734c64d011896031611bb0a9c249184b6feb54ca8c0ea80` matches the active manifest.
- R2 activation receipt `docs/handoffs/us_hk_700_supplement_20261016/runtime-activation-receipt-r2.json` SHA256 `3af07836db36e07d70f3430d7fe6479e1cc63c6a29a7a81064d580e7538ec1b8` records `ACTIVATED_API_READBACK_OK`.
- Switch: old PID(s) 23391 exited; label absent; 2-second settle; bootout and bootstrap both exited 0.

## Live readback

Default mapping API GET returned HTTP 200, 619286 bytes, SHA256 `ee1805b1b28bbf14fe79918c7f9454bb8f73958451eb9e6f34b6e51a86bd4450`: 667 stocks / 1,003 relations, 700 source-reviewed / 303 unprocessed / 0 independently verified.
R001 returned HTTP 200 as `SOURCE_REVIEWED` / `FULL`; 4 evidence rows contain both required evidence keys (`declared_unresolved_navigation_reference_json`, `evidence_wording_clarifications_json`).
R700 returned HTTP 200 as `NOT_PROCESSED` / `SUMMARY` / `review_revision=null`.
Research safety remains `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false.

`/manager-selection/` returned HTTP 200 and its entry SHA matches the R2 candidate. The referenced JavaScript asset also returned HTTP 200 and its SHA matches the R2 candidate:
- Entry: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-mapping700-20261016-r2/app/apps/web/dist/manager-selection/index.html` SHA256 `8a2d47ea8616e5b7f658bd150947bad7674cf9153ab559e8f33a297ff8d68a9e`.
- Script: `http://127.0.0.1:8873/assets/managerSelection-CnQlnjWW.js` -> `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-mapping700-20261016-r2/app/apps/web/dist/assets/managerSelection-CnQlnjWW.js` SHA256 `002f4dbd045590dd13331a231de453d5d2e39c6f1282a2097af38f7f397fba59`.

**CANNOT_CONFIRM:** rendered UI after the cutover (controller CUA pending), natural-time behavior, and independent semantic fact acceptance. No new plan or selection run was created; scheduler, 8910, and other services were untouched.

Full machine-readable details and response hashes are in `LIVE_DEPLOYMENT_RECEIPT.json`; exact cutover details are in `runtime-activation-receipt-r2.json`.
