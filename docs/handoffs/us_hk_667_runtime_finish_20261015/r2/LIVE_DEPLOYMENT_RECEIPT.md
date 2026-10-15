# Local research deployment receipt

Status: **DEPLOYED / API_VERIFIED** by deployment writer. Source and prepared-runtime independent reviews passed. A separate reviewer is checking live API; the controller owns the rendered UI receipt. No natural-slot acceptance or new saved plan is claimed.

Active release: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-mapping-finish-20261015-r2/app`.

- PID `99039`; process cwd and command read back from lsof/ps.
- Interpreter: `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python -B`.
- Manifest SHA256 `5c6e18640443c65d647e5072ce82472de2f813ef35d245065006ba44a1fe8684`.
- Active plist `/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist`, SHA256 `579d18f1d3fa5cde7b26787936fe0e43969a9f826485f55ca39deb8eb910916e`.
- Config `/Users/lexi/Library/Application Support/com.lexi.v4.local/config/manager-workbench-v9.json`, SHA256 `48fd88d8bc8921181a67c059af7907a56c6a78ef20bec480338409e553e60a9d`; only relation_root differs from v7.
- Successful switch completed `2026-10-15T15:18:56.631602+00:00` (23:18:56 Hong Kong time).

The existing shared release lock protected fresh plist/config/manifest CAS checks, atomic installation of exactly reviewed staged bytes, and postflight `active_pointer="candidate"` verification. Only `com.lexi.v35.api-only` /8873 was restarted. No scheduler, 8910, pool, scoring/BUY logic or owner source was changed.

## Live readback

All catalog cases returned HTTP200. Default response is **611266 bytes**, 667 stocks /1003 original relations,25 stocks on the page, SUMMARY relations. Progress:220 source-reviewed relations /92 stocks /89 stocks with every original relation recorded /783 unprocessed /0 independently verified. R001,R021,R137 each return one FULL relation whose complete review_revision equals its frozen overlay record. Their response sizes are83778,118225,75483 bytes. Safety flags remain RESEARCH_ONLY=true, production_allowed=false, buy_gate_updated=false, orders_sent=false, prediction UNTESTED, historical PIT NOT_VALIDATED.

`/manager-selection/` HTTP200 references `managerSelection-aigkxKal.js`; `/` HTTP200. Existing HK-history audit query for HK.00001 on20261014 returned HTTP200 with owner snapshot and research-only/PIT/scoring limitations. Current industry/history/us-close/native48 code is preserved by the exact10-path deployment and independent candidate inventory verification.

The existing US owner artifact remains byte-identical at SHA256 `4f50c61a68645cfa19c39fb8c92144ad69525183a81219ae833df80573fe6480`: READY,48 quotes, session20261014, original capture2026-10-15T06:09:12Z. No recapture or relabelling occurred.

The existing saved recommendation run `8984a72d3d134611a8ef7ea93364380d` still reports its historical US_MAPPING_EXACT_DATE_BINDING_MISSING. It was not rewritten. Per controller's final scope, no additional plan was created solely to change that status. Catalog availability and a saved stock-selection plan are separate deliverables; factor/relationship research gaps remain.

## Preserved startup failure and recovery

First attempt acknowledged bootout, but immediate bootstrap returned exit5 Input/output error; immediate rollback bootstrap returned the same error. The exact original us-close plist bytes were restored. A later bootstrap of those unchanged original bytes succeeded; PID98984 listened on8873 and the manager page returned200. The failure is retained in `activation-receipt.json`.

The second attempt confirmed old PID98984 had exited and the label was unregistered, allowed a2-second launchd removal interval, then bootstrapped the same independently reviewed staged bytes successfully. Both launchctl exit codes were0. See `activation-receipt-attempt2.json`; no permissions or unrelated services were changed.

Evidence: `LIVE_DEPLOYMENT_RECEIPT.json`, `live-api-evidence.json`, the two activation receipts, and `RUNTIME_HANDOFF.json`. Rollback remains exact `preimage/active-us-close-api.plist` (SHA256 `0f9118056d12804846ed70ab99a4cc0896363d435a4b753a5709182ef3348543`) under the same shared lock and a fresh current-candidate CAS. It restores the us-close release/v7 selector and preserves all raw artifacts and old plans.
