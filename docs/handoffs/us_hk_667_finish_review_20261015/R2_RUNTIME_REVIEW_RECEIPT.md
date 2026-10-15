# Independent r2 runtime-candidate review

Verdict: `REVIEWED=PASS`; `TESTED=PASS`; `BEHAVIOR_VERIFIED=PASS` for the prepared r2 candidate artifact, its pinned-runtime in-process API, and the staged switch/rollback bindings. P0/P1/P2 findings: none within this preactivation scope. The candidate remains **not activated**. Live `API_VERIFIED`, rendered `UI_VERIFIED`, `DEPLOYED`, and `NATURAL_VERIFIED` are not claimed.

Reviewer: independent task identity `mapping_220_final_review`, Luna Max. Review date: 2026-10-15. Candidate: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-mapping-finish-20261015-r2`; manifest SHA256 `5c6e18640443c65d647e5072ce82472de2f813ef35d245065006ba44a1fe8684`.

## Release and Vue integration

- Re-ran `ops.api_release_integration.verify_api_release_candidate` against the currently active plist with `active_pointer="base"`: **PASS**. The current base remains `us-close-recovery-api-20261015-r1`, manifest SHA256 `1dae9b975c4ecfe4fbf20900507877ce02de564684a0251060c73a2d618428ca`; candidate inventory is 1,213 entries. The verifier confirms the exact 10 delta paths and preserves all 1,203 non-delta entries, including their bytes and modes.
- Reviewed the active-to-candidate API and Vue diffs. The API adds the catalog import, paths, and read-only route. Vue adds the catalog tab, helpers, and panel; the existing industry helper and industry template remain present. No us-close producer, industry, HK-history, native input, engine, pool, or BUY path is in the delta.
- Candidate `manager-selection/index.html` and `managerSelection-aigkxKal.js` match the saved isolated build artifact byte-for-byte (SHA256 `a33757eceaef8e354076c5c02bf0dad04c0a6dc7b228b2539002a311c792ad7f` and `c3376748f2c217eba0e848e172fd27ffdad136a0eedd8d8dcd7aedbce543b8bf`). The HTML references that asset, which contains the on-demand detail and usage-limit labels. The release verifier confirms main HTML and all other non-delta app content remain on the active base. This verifies the packaged build artifact, not a rendered browser page.
- Reused the independent source receipt [POST220OPT_REVIEW_RECEIPT.md](../us_hk_667_finish_review_20261015/POST220OPT_REVIEW_RECEIPT.md) for the frozen 220-source semantics and its 12 Python tests, Vue test, and source type check; this runtime review did not repeat those source checks.

## Candidate API

Using the pinned runtime interpreter `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python -B` from the candidate app, an in-process FastAPI `TestClient` returned:

- Default query: HTTP 200, 611,266 response bytes, 667 matching stocks, 25 stocks on the page, and all 66 returned relation rows marked `SUMMARY`.
- Exact-RID queries: all 220 relation IDs returned exactly one `FULL` row whose complete `review_revision` equals the corresponding overlay record. The catalog progress and safety fields matched the default response for every RID.
- Progress remains 220 source-reviewed relations / 92 stocks / 89 stocks with every original edge recorded / 783 unprocessed / 0 independently verified. Safety remains `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`, prediction `UNTESTED`, and historical PIT `NOT_VALIDATED`.

These requests ran against the candidate module in-process; they did not reach the active local service.

## Selector, CAS, and rollback

- The actual active plist SHA256 is `0f9118056d12804846ed70ab99a4cc0896363d435a4b753a5709182ef3348543`, matching the frozen rollback preimage byte-for-byte. The release verifier independently reads the active pointer as `base`; no CAS change was observed.
- Config v7 still matches its frozen SHA256 `65684e5eb7657390747c089db74047d6a2c67d7f5de1bd3fe757a62f120965ca`; config v8 still matches the prior r1 receipt SHA256 `8b8e2a415170452b47c350949481dc8ca444412d0a8b8ef788987b1b21a62de9`. Config v9 SHA256 is `48fd88d8bc8921181a67c059af7907a56c6a78ef20bec480338409e553e60a9d`; its only leaf difference from v7 is `/relation_root`, which points to the r2 app. The v7 selector points to an older worktree root and v8 to the prior mapping r1 app, so r2 must use v9.
- The staged plist SHA256 is `579d18f1d3fa5cde7b26787936fe0e43969a9f826485f55ca39deb8eb910916e`. It retains service label `com.lexi.v35.api-only`; after normalizing only release/app/manifest and v7-to-v9 config routing, its full structure matches the active plist. Because v9 changes only `relation_root`, shared state, source, stage, and capture roots are preserved.
- The prepared cutover record binds the candidate manifest, staged plist, current base, shared release lock, and exact rollback plist. Its state is `NOT_ACTIVATED`, `launchctl_called=false`; no service or pointer was changed and no new manager plan was saved in this review.

## Current base evidence and limits

The current-base `candidate-writer-canary.json` records the owner capture as READY with 48 quotes, source session `20261014`, and SHA256 `4f50c61a68645cfa19c39fb8c92144ad69525183a81219ae833df80573fe6480`. Its in-memory native result at cutoff `2026-10-15T23:08:55.437869+08:00` is `PARTIAL`, 60 rows: 13 `NOT_SELECTED` and 47 `UNASSESSED`; the paired-factor identity and relation gaps remain. This review uses that current-base receipt and does not apply the older 40-capture `CANNOT_CONFIRM` to the r2 base. The reviewer did not modify or independently recapture the shared raw artifact or producer.

Live service response, rendered page behavior, a service switch, and a natural slot remain unverified. Independent company-fact verification, prediction/backtest/PIT acceptance, and old-997 comparison remain outside this receipt.
