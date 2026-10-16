# Announcement HK Connect admission repair

Announcements previously entered the local Qwen queue without an HK Stock Connect membership check. This patch reuses the existing authoritative full-universe reader and binds the target date, cutoff, authority SHA, version, effective interval and member hash before admission. Nonmembers and unknown eligibility are excluded before enqueue, queue execution or model transport. Missing, stale or changed authority evidence fails closed.

Historical and incremental candidate projections apply the target-date membership check while preserving original results and the pinned target date as CANNOT_CONFIRM. The UI reports authority provenance and excluded/unknown populations. It does not confer BUY eligibility.

## Patch and runtime identity

`source-delta.patch` contains the eight scoped source/test file deltas against the actual `hk-morning-selection-recovery-20261016-r6/app` runtime base. `file-shas.json` gives exact before/after SHA-256 values and paths. This is a scoped handoff patch, not a full standalone deployment tree. The canonical source checkout is `/Users/lexi/Desktop/学习/v4_app`; the deployed overlay preserves active-only TypeScript fields that differ from that checkout.

Git handoff parent: `8512d766217988929a40350f539fe165a76a2170`. Local release: `announcement-connect-api-20261016-r2`; manifest SHA `63d1244ec11aa81d74ade566c42da41947ed0a580b2f27ea74b2f286e77dd089`. All 1,220 non-delta inventory entries are preserved, including the concurrent API recovery change. The first candidate was not activated because independent review found a target-date provenance issue; r2 corrects it.

## Validation and boundaries

Independent review reran 23 backend tests and one frontend test for r1, then reran the two changed backend regressions and the frontend test for r2. The actual runner path with OUT/UNKNOWN-only synthetic inputs recorded zero enqueues, zero queue runs and zero transport constructions. The date regression preserves the base CANNOT_CONFIRM alongside separate membership and incremental target dates. The writer full suite passed 24 tests; Vite production build passed. Five pre-existing TypeScript diagnostics in unchanged files remain outside this repair.

Live API and the reloaded Codex in-app browser show 15 eligible stocks, five excluded stocks and zero unknown stocks for membership target 20261016. Existing raw articles, model results and queue history are preserved. The interrupted job remains FAILED with 38 succeeded, 117 pending and one residual RUNNING item; that residual is not treated as completed. No new capture, model call or old-queue retry was performed for this repair. Natural new-batch validation is NOT_RUN. Selection semantics and BUY eligibility are not promoted.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.

Only source/test deltas, hashes and compact acceptance metadata are included. Raw announcements, model outputs, queue files, credentials, operator configuration, LaunchAgent files and built assets are excluded.
