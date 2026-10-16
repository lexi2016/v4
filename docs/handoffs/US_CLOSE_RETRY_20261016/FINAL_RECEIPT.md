# US close recovery and bounded retry — final delivery

On 2026-10-16 at 12:42:57 Asia/Shanghai, the existing US producer completed a controlled late capture of US session 20261015 into research date 20261016. The verified artifact has READY 48/48 quotes and 24 theme rows. The API and reloaded stable V4 page show target/snapshot 20261016, source 20261015, POST_CLOSE and 48/48 coverage. This is manual late recovery, not natural scheduled-run acceptance.

## Incident and repair

The 04:15 executor used the US session as the research artifact key, merging into the previous research day's payload and failing provider-session validation. The 05:15 dispatcher succeeded only as NOT_DUE and did not recover the failed close. The repair separates business/artifact date from provider session and permits one unused paired inactive-slot retry after an exact hash-valid failed POST_CLOSE receipt: summer 04:15 → 05:15; winter 05:15 → 21:00. PRE_OPEN and consumed receipts remain protected.

Live recovery exposed two integration omissions: the manual command initially lacked the configured owner root (producing legacy V2/33), and repeated POST_CLOSE snapshots lacked a unique matching capture identity. The final owner-bound command uses the existing V3/48 contract. The final merge helper places the selected timestamp's capture first for the existing store and binds its capture_id/run_id for the existing API consumer. Store/API validators were not weakened or changed in the running release.

## Actual identity and evidence

- Canonical source root: `/Users/lexi/Desktop/学习/v4_app`.
- Git handoff baseline: `58487a65eff225f38361de4660385583bf531356` in private `lexi2016/v4`.
- Actual deployed US app: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-close-retry-us-20261016-r3/app`.
- Runtime: `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python`.
- Old actual release manifest: `a22b7e6079fd701e996f73f8c0e8ab37610f7127bd0d5516b293e7dd3b31b1f2`.
- Intermediate R1 manifest: `3793d0acb6937828fccc0c6f1a5331be699e7ad62ac448654050a62ab70225a9`.
- Final R3 manifest: `592bb39ce93fd9d564d34088403d96fd14213c2380991b239a458e80c72a9139`.
- R3 phase_merge SHA: `daf48ff122eb46368fa909562cad86c25106c0cc2072fcfa462d9275544e181b`; R1 preimage: `0503d21b0ed348c825da70a2fd650aacf2e52306c2c083a74ca5e4882c95d464`.
- Active US plist SHA: `d9cc2ea72a17177a5054d1034a9a361af4cf10b5a08036b476ade505ffc74f7d`; loaded by launchctl at 12:43:35. Existing four calendar slots unchanged; RunAtLoad=false. No other service was changed by this activation; concurrent changes to other owners were observed and preserved.
- Final capture run: `20261016T044257Z-7de79788100e4ca6a666e09083ded1ce`; receipt SHA `0aa1c911c823d0143f0a00533ca97a3ceb96e652d264b4b7cec03b5a3c3476e8`.
- Final payload SHA: `3753d3bb99d7a585587e01bc92c903d2c0920cffbf1c686dc4bea58f76eed4da`; capture `78b032efbb6b25a3a8a80693`; run ID `us-rss:20261015:POST_CLOSE:78b032efbb6b25a3a8a80693`.
- Exact previous V2/33 and V3/48 payloads remain in content-addressed history: `e65a6e82e21f7cba1667be19e01957184da6e415c329bbeb9ee5f4f934a3c368` and `3c395a48f7d5d52f49e52cbbe77859bde661719b9bc01dfc1664e53a1f01c8c3`. Supersession links were read back. Three capture records remain in the final artifact.
- Previous date's payload and original 04:15 FAILED / 05:15 NOT_DUE receipts retain their original hashes.

## Independent acceptance and limits

Independent Luna Max reviewer receipts in `reviewer/` establish the scoped results. Initial date/retry candidate tests: 11 passed; evidence/legacy/CAS/collector suite: 10 passed. Final focused source regression: 11 passed. Temp full-producer plus actual API-r4 consumer canaries reproduce the R2 ambiguity and pass R3 READY 48/48. Final live receipt `R3_POSTINTEGRATION_READBACK.md` independently verifies controlled capture, current API, rendered UI evidence, protected history, and loaded R3 identity. No further business-code tests were run after these scoped PASS signals.

Status: IMPLEMENTED, TESTED within the stated suites, REVIEWED (target-scoped PASS), INTEGRATED, DEPLOYED, API_VERIFIED, UI_VERIFIED, and BEHAVIOR_VERIFIED for this controlled recovery. NATURAL_VERIFIED is NOT_RUN; future automatic execution/retry is not yet naturally proven. RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.

Known P2 backlog: two different valid capture IDs at exactly the same timestamp can be misbound by first-match selection. The reviewed and actual target captures have distinct timestamps; the final run checked this before execution. The edge was not broadened into this bounded recovery. GOOGLE_NEWS_RSS_DISCOVERY_ONLY remains CANNOT_CONFIRM. Older packaged-test/RSS-only compatibility failures documented in prior reviews are unchanged and outside the close-retry acceptance.

## Delivery layout

Apply `candidate-runtime.delta.patch` to the hash-pinned old actual US release, then `R1_TO_R3_PHASE_MERGE.patch` to obtain the final business delta. The first patch is old actual release → R1; the second is R1 → R3 (one helper). They are not patches against an arbitrary dirty canonical checkout. `source-postimage/` carries the necessary canonical validator/test bytes. Complete canonical preimage bytes were unavailable for some files; `SOURCE_ONLY.patch.README.md` records that limit. The final deployed release, canonical source, and earlier candidates are not interchangeable.

The earlier R1 activation/manual script and earlier review receipts are historical evidence; the final activation helper is `candidate/evidence/us_only_cas_activation_r3.py`. It is pinned to the completed R1→R3 operation and must not be rerun against the already-activated R3 state. The real final capture used the reviewed collector with explicit R3 owner/config/proxy environment and the existing producer arguments `--trade-date 20261016 --us-session-date 20261015 --capture-phase POST_CLOSE --allow-late-post-close --manual-late-recovery`.

`DELIVERY_SHA256.json` is the final Git-delivery index. Earlier working checksum ledgers contain superseded entries and are not final acceptance indexes. Raw quotes/RSS data, actual plists/configuration, credentials, dependency environments, and unrelated workspace changes are excluded from Git delivery.
