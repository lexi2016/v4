# US-HK mapping catalog delivery — 2026-10-15

The cumulative220 catalog is implemented, independently tested/reviewed, integrated and deployed to the existing local V4 on 8873. The controller verified the rendered catalog, RID search, on-demand full record, and source limitations. Independent live runtime/API verification passed. No natural-slot or full company-fact acceptance is claimed.

Canonical source root: /Users/lexi/Desktop/学习/v4_app. Active app root: /Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-mapping-finish-20261015-r2/app. Live PID at delivery: 99039. Release manifest SHA256: 5c6e18640443c65d647e5072ce82472de2f813ef35d245065006ba44a1fe8684. Config v9 SHA256: 48fd88d8bc8921181a67c059af7907a56c6a78ef20bec480338409e553e60a9d. Runtime predecessor: us-close-recovery-api-20261015-r1; exact 10-path integration preserves 1203 non-delta entries. Git handoff baseline: de51a794173cd4d48ac607da36e41a241fe51a83.

## Delivered behavior

- All 667 stocks / 1003 original relationships remain browsable and searchable by HK code/name, US asset or relation ID. Pagination does not truncate the research input or change totals.
- Complete batch11 source package SHA256 8a214c3c10931e2ab807a3f1701449105702c68186a07a3c1da717413e69fab1 binds 220 source-reviewed records / 92 stocks / 89 stocks with every original edge recorded. 783 relationships remain unprocessed; independently verified total stays 0.
- Default response drops from 4784175 to 611266 bytes (87.22% reduction). Warm in-process serialization-inclusive mean: 56.83 to 9.56 ms; this is not a browser network latency claim. Full source evidence loads by exact RID with identity validation and stale-response rejection.
- Original fields, revisions, clickable original sources, use restrictions, current gaps and later conflict addenda are retained. Overlay SHA256 stays 72a0f074e6412036cd103c7f73ccf15230eb3d1633c09742c88653b863eba384.

## Acceptance and limits

Independent source acceptance: 12 Python tests, Vue component scenario and targeted TypeScript verification. Independent prepared release check: exact delta preservation and all 220 FULL revision records. Independent live checks: actual PID/cwd/interpreter, plist/manifest/config identity, GET catalog and FULL R021. Controller rendered checks: default totals, R001 on-demand detail, R021 query and expanded Hyatt metadata conflict, safety footer.

The first immediate launchd bootstrap returned error5; exact original service was restored. A second bounded switch confirmed old process exit and label removal, waited for launchd settling, and succeeded. Both attempts and recovery remain in local runtime evidence. No unrelated service was restarted.

Batch28 cumulative560 only has part2of2; batch35 cumulative700 only has part3of3. These partial volumes are not ingested or mixed. Source researcher results are not full independent fact acceptance. Twelve targeted semantic spotchecks are non-blocking with flags; R023/R143 inaccessible primary PDFs remain CANNOT_CONFIRM. Prediction UNTESTED, historical PIT NOT_VALIDATED, natural-slot NOT_RUN. The old saved intraday plan retains INPUT_MISSING and was not rewritten. No new saved plan was made for a green status.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false. HK preselection work was cancelled at the user's request; no pool change was made in this delivery.

## Evidence and GitHub scope

See ../us_hk_667_finish_review_20261015/{POST220OPT_REVIEW_RECEIPT,R2_RUNTIME_REVIEW_RECEIPT,LIVE_RUNTIME_REVIEW_RECEIPT,UI_RUNTIME_RECEIPT,BATCH220_SEMANTIC_SPOTCHECK,VOLUME_INTAKE_RECEIPT}.md and ../us_hk_667_runtime_finish_20261015/r2/LIVE_DEPLOYMENT_RECEIPT.md. Exact source SHA and diffs are in post220opt/postimage_manifest.json and delta_from_catalog40.diff; exact active-to-runtime integration diff is in the r2 handoff.

Private GitHub branch: codex/us-hk-mapping-finish-20261015 at lexi2016/v4. Sync contains necessary source patches/builders/measurement helpers and compact evidence. Patches are stored as handoff artifacts, not applied to the remote repository's application files; no merge is claimed. Bulk research JSON, ZIPs, raw market data, generated JS/dist, credentials and environments are excluded. Final remote head and byte-for-byte readback are recorded separately in GITHUB_SYNC_RECEIPT.json.

## Controller lifecycle ledger

- us_mapping_finish_writer: post220opt implementation; final consumed; receipt verified; COMPLETED.
- mapping_220_final_review: source, candidate, live independent acceptance; separate receipt per milestone; final consumed on final handoff.
- us_mapping_runtime_plan: runtime integration and local activation; final consumed; live deployment receipt verified; COMPLETED.
- us_mapping_220_semantic_audit: 12 primary-source spotchecks; final consumed; receipt verified; COMPLETED_WITH_FLAGS.
- mapping_volume_intake: partial-volume intake; final consumed; receipt verified; COMPLETED.
- hk_preselection_triage: CANCELLED at explicit user stop; no writes.

Simple intake and independent acceptance use Luna Max; complex integration and semantic investigation used the user's explicitly allowed 6.1 Sol High tier. All roles retain single-writer and independent-reviewer separation.
