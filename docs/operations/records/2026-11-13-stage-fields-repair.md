# 2026-11-13 Stage 0925 card context repair

Status: CANDIDATE_IMPLEMENTED / TARGETED_TESTED. Independent Reviewer acceptance, deployment, loaded UI and natural-run verification are NOT_RUN. No commit, push, service, scheduler, source archive, selection, ranking, score, eligibility or trading changes were performed by Writer.

- Writer worktree: `/Users/lexi/.codex/worktrees/stage-fields-20261113/v4_app`
- Branch: `codex/stage-fields-20261113`
- Base: `60457d189b130a7050942addee60d7e694d57b15`
- Exact API-role base: `v4-workbench-quote-contract-20261112-r1-api`; frozen `docs/source-baseline-20261112/roles/API.json`.
- Test candidate: `/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-stage-card-context-20261113-r1/api/app`. It has no running listener; TestClient invokes the actual `create_app` assembly in process.
- Original live source and canonical dirty tree were read only. All source editing took place in this independent worktree and the controller-owned, temporarily delegated inactive candidate.
- Scope: A-share native `STAGE_0925` supplementary card evidence. Original SelectionStore artifacts and HK rows remain unchanged. `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.

## Reproduction and sources

The controller's frozen response is `/Users/lexi/Desktop/学习/agents调试/v4_stage_missing_fields_20261113/before_20261113_0925.json`. Its source evidence contains a native snapshot route and captured_at but no `v4_stage_cutoff`. The old news projection therefore reports a missing/conflicting cutoff although the exact source snapshot and `contracts/stages.py` bind `2026-11-13T09:25:05+08:00`.

The new resolver verifies the exact native date/stage, manifest schema, manifest snapshot relative path, snapshot raw SHA against both manifest and selection source evidence, capture identity and the original cutoff. It does not read the wider 09:20-09:30 scoring-window label as a news boundary. Missing/conflicting/future/tampered bindings stay closed.

Original native snapshot:

- Path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data/stage_inputs/native_opening/20261113/STAGE_0925/snapshot.json`
- SHA256: `bec331c93bf9c9787b8f874adc687369e9931d45447aa6580c77a41362c9db21`
- captured_at: `2026-11-13T09:25:00.586103+08:00`
- cutoff: `2026-11-13T09:25:05+08:00`

Verified morning-news root: `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data`.

- Exact date run: `20261113-morning-news-279bfb2b73fa`.
- Payload semantic SHA: `279bfb2b73fa1efc3dbc541fbb835707958aa32874dd0f5ca4ecc8b90bddf7aa`.
- Articles SHA: `a24964166576d5ef7c95bea12eec7018066520baeb10edb96ad94b73228dc6d8`.
- Original source-input SHA: `78080593cbae4db2cafc41eab76f2376bd32f3361b00668a81b1fe80d117f324`.
- Both 国统 A.002205 and 洪通 A.605169 have two body matches: `https://www.jiuyangongshe.com/a/20dw7p5hnlw` at 07:06:33 and `https://www.jiuyangongshe.com/a/jzysy7d02e` at 07:24:02, on 2026-11-13.
- Existing parser yields supplemental news score 48; original `news_quality_score` and stage score remain untouched. `pit_capture_verified=false` is retained and shown. The parser's incidental research score 36 is never used as an original research score.

## Exact legacy warning representation compatibility

Actual same-day reader first failed `RESEARCH_SOURCE_WITNESS_INVALID:SOURCE_ARCHIVE_PROJECTION_SHA_MISMATCH` for 0900. This occurred in both the canonical and live API-role readers.

- Archive: `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/research/hourly/live/20261113/0900.json`.
- Receipt: `.../receipts/research/hourly/live/20261113/0900.json`, SHA `3dfe63e2d8b9a609d67077d473c3802c530fd301d5b12214f4de16493caaac92`.
- Archive/base SHA expected: `d0b0212f3c22338974a46c341b9b17fd248cbf51b9135baf63d9d7952c8b2386`.
- Source witness: `.../research/hourly/source/51c82433cac954ed09d9548c53f6c640f7dfb8efc5e3e47cc767154a43b20a76.json`.
- Source witness expected SHA = actual raw SHA: `51c82433cac954ed09d9548c53f6c640f7dfb8efc5e3e47cc767154a43b20a76`.
- Current expanded reprojected SHA: `23d04c71cf85b21599814c78b5c8a6b3cd1320b0eb57d2e2c2560853225b4f38`.
- The sole differing top-level field is `cannot_confirm`: old archive has `LEGACY_SOURCE_CANNOT_CONFIRM_COUNT:891` plus 79 source-audit report-role warnings; current converter expands the source gaps.

The helper reconstructs only the known old representation. The old count rule is present at base `tests/fixtures/research/commits/ce9b94199b06c8d489f72dd9ed8697cb9bbcf82f/domains/research.py:245`. The strict source-audit warning projector is reused from base `domains/research.py:161` (file SHA `965ca283bf04f0746142fb56a7c5992ab6904fbf46686c7934b241fafccb6fb1`). Its affected-code list must match individual excluded evidence with unique IDs and declared receipt paths; unknown policy or malformed audit is rejected. The API-role builder lacks this projector, so the same pure function is included in the narrow helper rather than replacing that role's domains module.

All fields other than the warning representation must already match. After exact warning reconstruction the complete base payload SHA must match the archive. Raw source SHA, identity, date, original reader time/PIT checks and subsequent field lineage checks remain active. Original artifacts and warnings are not rewritten; archive warning list and expanded-gap SHA remain in supplementary provenance. No other mismatch permits fallback or relaxed comparison.

After this compatibility, original 0900 archive is readable. 国统 and 洪通 are absent in both 0830 and 0900 original article/pool records: their research score stays null and UI says `09:00 研报归档无该股记录（已核验）`. Boundary sample 天安 A.603725 is present in 0900 but has no original item quality scalar; it remains null with that exact reason. No synthetic research score is supplied.

## Structure gap

All three representative rows have null original support/pressure/invalidation and null native open/high/low fields. D-1 original `anchor_role.csv`, `prior_plan.csv`, `theme_stocks.csv`, `intraday_handoff.csv` do not define these three structural price fields; `theme_stocks.price` is an ordinary reference quote. The 11/12 research panel contains 洪通 with a 2026-10-30 key-K anchor and OHLC, but does not declare those as support/pressure/invalidation; its historical PIT flag is false. 国统 is not in that panel's selected product rows. These facts are not turned into a new price model or copied into 0925. All three fields remain null, and the card reports the verified-source gap. Structural-value completion is CANNOT_CONFIRM.

## Role-specific integration

Normal worktree source changes and before/after SHA are in `2026-11-13-stage-fields-root-sha.json`. API-role changes and exact original/after SHA are in `2026-11-13-stage-fields-role-sha.json`.

- Copy shared `stage_center/news_link_projection.py` and the new `stage_center/stage_card_context_projection.py` into the exact API-role candidate.
- Normal `apps/api/v4_api/projection.py` is derived from frozen API SHA `8e140347962d4baf63c43137950f8e78142a56ab8b68cea32e01b117811b78ac`; the only semantic changes are the optional resolved research root in ProjectionContext and forwarding it to the card projection.
- Apply `2026-11-13-stage-fields-api-app.patch` to exact API `apps/api/v4_api/app.py` SHA `7c7d653e1797c5d294e04aade4bc015c3feac573dd65c0ed02980f1376ebf9db`: one constructor argument forwards the actual configured research root. Do not use V4 store.root as its substitute.
- Apply `2026-11-13-stage-fields-api-role.patch` to exact API-role research context and frontend App/Types. It adds the same compatibility call, exposes the already-validated actual source-generated timestamp, and applies only the small common card UI delta. It does not replace role files with their differing canonical variants.
- Canonical `apps/api/v35_api/app.py` gets only the analogous call argument to avoid future regression.
- Frozen source-role overlays are untouched.

These changes have already been applied to the delegated inactive candidate; patches are provided for review/reproduction, not to apply twice.

## Actual validation and results

Project PANEL_PYTHON: `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python`. Exact API role was tested with `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python` and candidate PYTHONPATH.

1. Canonical targeted Python suite: `PANEL_PYTHON -m pytest -q tests/test_news_link_projection_20261014.py tests/test_stage_card_context_projection_20261113.py --basetemp=<task-specific dir>`: 19 passed before final two negative cases. Initial fixture failures (missing source item identity / invalid test article field) were corrected in the test fixture. A first run also hit pre-existing shared pytest garbage cleanup EPERM; subsequent runs use this task's own basetemp and do not alter unrelated locked files.
2. Final exact API-role suite, cwd `/tmp`: `PYTHONPATH=<candidate> <v4-mac-python> -m pytest -q <worktree>/tests/test_news_link_projection_20261014.py <worktree>/tests/test_stage_card_context_projection_20261113.py --rootdir=<candidate> --basetemp=<task-dir>/pytest_writer_final_api_role`: **21 passed in 0.12s**. Covers real morning parser and SHA chain, native cutoff conflict, wrong date, missing manifest, future capture, unknown warning/count, archive title/score changes, forged source quality/raw SHA, future source-generated time, unknown audit policy, missing research, immutable original rows, HK bypass and a verified original 72.5 fixture research score as a separate supplement.
3. Actual API-role frontend DOM test: `npm test -- --run src/App.stage-fields-20261113.spec.ts`: **1 passed**. It renders the real App component with the stage API module mocked at its boundary, checks original stage100, news48 links/time/PIT note, explicit research gap and structural gap. It does not claim network/UI deployment verification. The first trial's incomplete API-contract fixture was replaced by a module-boundary rendering fixture.
4. Actual API-role build: `npm run build -- --outDir /Users/lexi/Desktop/学习/agents调试/v4_stage_missing_fields_20261113/frontend_generated_dist --emptyOutDir=false`: **PASS, 115 modules, 782ms**. Existing node_modules was temporarily linked; no install/network dependency change. A stray npm invocation from repo root returned ENOENT and made no product changes.
5. Only the 3 generated HTML entries and 7 generated hashed assets were mechanically merged into candidate dist. **15 old non-delta dist files remain byte-identical; zero old files deleted**. Existing independent static/research-panel material and old hashed assets remain present. Receipt: `<evidence>/FRONTEND_MERGE_RECEIPT.json`.
6. Actual `create_app(data_root=<original V4 state/data>, stage_center_selection_root=<original V4 state/stage/selection>)`, using original plist environment solely within this child process, was exercised by FastAPI TestClient. Read-only `GET /api/v3/workbench/stage?date=20261113&stage=STAGE_0925&limit=50`: **200, 20 rows**. No listener, service, scheduler or live deployment was started. Result: `<evidence>/candidate_20261113_0925.json`; concise real sample proof: `<evidence>/WRITER_CANDIDATE_API_CHECK.json`.
7. The controller's frozen complete 20-row identity oracle was compared to candidate output: A10/HK10 original selection artifact/run/algorithm/SHA/receipt identity, all recorded original row fields, rank/score/stage score and eligibility remain identical. Receipt: `<evidence>/WRITER_SELECTION_UNCHANGED.json`. HK original selection dictionary remains identical to saved exact response.
8. `git diff --check`: PASS. Full historical suite, deployment, GUI, loaded UI, natural execution, Git commit/push: **NOT_RUN**.

`<evidence>` is `/Users/lexi/Desktop/学习/agents调试/v4_stage_missing_fields_20261113`.

This task's reconstructed review-source copy, generated external build dir and fixture basetemp directories were removed after results were recorded. The candidate-only test copy and temporary node_modules symlink were removed. Original source inputs, successful candidate, necessary receipts and frozen before/after evidence are retained. Cleanup receipt: `<evidence>/WRITER_CLEANUP.json`.

## Independent review focus / stop rule

Review exact API-role patches and common helper, not a whole canonical-to-role replacement. Check precise legacy warning reconstruction including the 79 source-bound audit exclusions, rejection of other payload changes, original cutoff09:25:05, root forwarding through create_app, score/selection invariance and preservation of static assets. The candidate handoff is not final acceptance.

STOP after independent frozen-scope PASS; do not expand into a new structural pricing model, historical warning/source rewrites, further compatibility variants, new producer or third-party collection. CANNOT_CONFIRM: actual structural price values, original per-stock research scores absent from verified archives, morning capture PIT, loaded deployed UI and natural-run behavior.
