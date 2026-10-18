# Issue45 / PR46 deployment acceptance — 2026-10-18

PR46 was merged into its actual base `codex/us-hk-source-baseline-20261018` at `475f9d6bb44d17b8bc948f755c3e7ba2b7b8a088`. The independently accepted changes are deployed to the existing local research services. Issue45 remains OPEN: deployment is verified, but the refreshed target result and a fresh natural close chain are not yet verified.

| Gate | Result | Evidence |
| --- | --- | --- |
| Candidate review and offline behavior | PASS | INDEPENDENT_REVIEW.json; manager 4/4 and API 13/13 focused tests, date boundary and catalog conservation checks |
| DEPLOYED | PASS | LIVE_INDEPENDENT_REVIEW.json records exact manifests, live plist hashes and process roots |
| API_VERIFIED | CANNOT_CONFIRM | Current target plan still uses the old US20261015 input; no refreshed exact-session result |
| UI_VERIFIED | CANNOT_CONFIRM | Reloaded page matches old run `5feb2dbf6d3c4b6b8598e9dae67af542`, INPUT_MISSING; UI_AFTER.json/png |
| Live BEHAVIOR_VERIFIED | CANNOT_CONFIRM | No valid US20261016 owner input exists for the historical catchup |
| NATURAL_VERIFIED | NATURAL_SLOT_UNVERIFIED | First pending fresh slot: 2026-10-20 04:15 Asia/Shanghai, US20261019 -> HK20261020 |
| Canonical source and GitHub synchronization | PASS | Exact11 canonical files match accepted staging; source commit `2cbb566da95f1956786a71b585d655f9635d21b9` and22 source/evidence files read back byte-identically; CANONICAL_APPLY_RECEIPT.json and GITHUB_SYNC_RECEIPT.json |

Final canonical source review is PASS (SOURCE_INDEPENDENT_REVIEW.json):30 focused tests passed,1 known baseline fixture-date failure was preserved, both POST_CLOSE date oracles passed, and all3 source patches reproduce exact deployed files. Canonical application performed a preimage check on all11 paths before writing and preserved modes. Compared with merged PR46, only the slot wrapper and its regression test changed; the other9 source/test files reuse the merged bytes.

GitHub source and compact evidence are synchronized to `codex/issue45-pr46-deploy-20261018`. The fixed verified source commit is [2cbb566da95f1956786a71b585d655f9635d21b9](https://github.com/lexi2016/v4/commit/2cbb566da95f1956786a71b585d655f9635d21b9); a documentation-only follow-up carries the final delivery and readback record. This does not imply another merge into the PR base. Screenshots remain local evidence.

## Actual deployed identities

- US digest: `issue45-pr46-us-digest-20261018-r2`, manifest SHA-256 `73db17d4a3d8af900f00ca056716a20f289b4df90b5f862d1207790f1a18e201`.
- Manager scheduler: `issue45-pr46-manager-scheduler-20261018-r2`, manifest SHA-256 `58e3f267ce1fec7af8104df379378a6f0b234faa2b6453174a12681ea0226969`.
- API: `issue45-pr46-api-20261018-r3`, manifest SHA-256 `40872d5013f2239b40821f8547e65bcfed0af58102efb16113a38f2f5bc401e9`.

All release apps are under `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/`. Canonical source remains `/Users/lexi/Desktop/学习/v4_app`. Existing release/config identities, runtime interpreter and shared data roots are distinct and must not be interchanged. Parallel Futu board and ZSXQ changes were preserved. The existing external relation root remains in use.

## Exact current gap

For required US20261016 -> HK20261020, the target-date owner artifact and receipt are absent. The manifest-bound fallback under `research/peripherals/20261016/external_finance.json` actually declares POST_CLOSE session `20261015`; its receipt agrees with US20261015. The deployed resolver rejects it as `US_OWNER_RECEIPT_ARTIFACT_SESSION_INVALID`. There is no matching US16 handoff cursor. This is missing valid upstream input, not evidence of a valid input being left unconsumed. The next fresh US19 slot cannot retroactively validate the missing US16 input.

The independent reviewer recorded exact artifact/receipt/manifest SHA in LIVE_INDEPENDENT_REVIEW.json. The old owner has 48 quote rows; that number is not the fixed-33 coverage denominator or the 1,003 catalog relations. Offline conservation of 667 catalog stocks and 1,003 relations retains UNASSESSED / catalog-observation boundaries and does not establish live selectable coverage.

## Bounded deployment events

The initial API bootstrap returned EIO while the previous process was still draining. The old plist was restored and the old service recovered; after confirming process exit and port release, the reviewed candidate activated successfully. This was a service drain race, not an observed source regression. The manager's later Sunday 11:00 failure was `hourly_research` with `HOURLY_RESEARCH_INPUT_NOT_MATERIALIZED`; it was not a US POST_CLOSE dispatch and did not indicate rollback. No manual capture, historical replay or notification test was used to manufacture acceptance.

The weekday POST_CLOSE date regression was repaired before activation: HKT20261020/0415 -> US20261019 -> HK20261020; the weekend/holiday case HKT20261017/0415 -> US20261016 -> HK20261020 also passes. Non-POST_CLOSE date behavior remains unchanged. Existing baseline test failures are preserved in INDEPENDENT_REVIEW.json and are not reported as a clean broad-suite pass.

## Pending natural verification

Current-thread heartbeat `issue45` is ACTIVE at 04:35 Asia/Shanghai Tuesday through Saturday. It checks the actual natural slot, owner and consumer identity/lineage, API and reloaded page, using an independent Luna Max reviewer. It stays quiet while unchanged and reports a new failure, recovery, completion or needed action. Issue45 stays open until the required natural chain passes; the monitor then updates evidence and pauses.

Safety remains `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`. No raw market data, complete overlay, credentials, runtime release directory or logs are to be uploaded to GitHub.
