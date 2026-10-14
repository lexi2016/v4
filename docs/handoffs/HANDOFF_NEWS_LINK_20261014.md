# News-to-stock association repair — 2026-10-14

Canonical source: `/Users/lexi/Desktop/学习/v4_app`. Private GitHub base: `6d3b440d43bd59e22f27eeef98e1d99b201d111d`. User requested a minimal direct repair with no subagents. Main agent implemented and validated; independent REVIEWED / TESTED / BEHAVIOR_VERIFIED: NOT_RUN by user instruction.

The shared morning-news consumer depended on a V1.9.2 candidate registry that was empty, despite valid exact-date archived news containing selected stock names. The stage API now supplies its verified SelectionStore stock identities to the existing body matcher and frozen news-score formula. Only identity fields are supplied; preselection/formal/research bonuses are not inferred. No network recollection, second producer, or source-file writes occur. The reader verifies the existing payload/manifest/receipt chain, excludes articles with unknown, other-date or post-cutoff publication time, and returns article and identity hashes.

This is a read-side supplement, explicitly labeled on screen: `补关联分未计入原阶段分`. Original news/research scores, ranks, stage scores, artifact IDs and immutable stage files are retained. Source capture time is not attested (`pit_capture_verified=false`); publication filtering is not retroactive PIT/natural attestation. No stage scoring producer, research scoring logic or HK logic changed. Missing research records remain null, with the exact consumed slot and code-local reason projected to the card. Empty/unverified news sources and unmatched names have separate reasons.

At `20261014 / STAGE_0945_1030`, the page now shows 龙版传媒 3 news links, 广电网络 3, 骏亚科技 2, each supplemental score 48 from the existing formula. The other 7 A rows have no matched news in this source/window. All 10 retain null research scores and show `10:00 研报归档无该股记录`. These are source-specific missing states, not claims that no report exists anywhere.

Runtime: `news-link-api-20261014-r2`, cloned from the concurrently updated active `mwb-wide-industry-r7-20261014-r1`. Only this repair's API hunk and reader/UI files were applied; parallel manager-workbench changes were preserved. Manifest SHA256: `f1cb7572596c988b528a499e13e602ca58470cc003a92695e6580c9263aaad5d`. LaunchAgent: `com.lexi.v35.api-only`, local port 8873. Stage scheduler was not reloaded. The scoped branch is a source handoff, not a standalone release image.

Validation:
- Canonical Python: `.venv/bin/python -m pytest -q tests/test_news_link_projection_20261014.py tests/test_stage_morning_root_wiring.py --basetemp <isolated-temp>`: 15 passed. Default pytest cleanup hit pre-existing protected temporary files; isolated temp rerun passed without changing their permissions.
- Actual deployed Python runtime and candidate imports: targeted `tests/test_news_link_projection_20261014.py`: 7 passed. Tests cover real matching, no mutation, malformed/tampered source, unverified selection, absent date, late/other-day/unknown publication and existing zero scores.
- Web: `npm test -- src/App.spec.ts -t 'supplemental news|news and research quality'`: 2 passed. An unrelated pre-existing A/H review test (`0.2 模型`) failed in the broader suite and was reproduced with the pre-change App.vue and original test file; left outside scope.
- Candidate production Vite build: passed. Candidate release identity validation: passed.
- Live exact-date API: original fields and A/HK selection run IDs/SHA unchanged; three news associations confirmed; production_allowed/buy_gate_updated/orders_sent remain false.
- Reloaded original browser tab: verified all 10 A cards, supplemental notes, real research gaps; screenshot and text saved locally.

IMPLEMENTED / INTEGRATED / DEPLOYED / API_VERIFIED / UI_VERIFIED. NATURAL_VERIFIED not claimed; read-only historical projection requires no scheduler replay. No subagents used.

Local evidence: `/Users/lexi/Desktop/学习/agents调试/V4_NEWS_LINK_20261014` (scope, before/after source SHA, targeted tests, baseline failure, release activation, before/after API, ui.txt/ui.png). Raw news, full API responses, runtime artifacts and local plists are excluded from GitHub.

| Source | Before SHA256 | After SHA256 |
|---|---|---|
| `infrastructure/shared_morning_news_reader.py` | `6f99c9052c93484c6ce6e70b6c2978be53b23f57c0f4e2cd68140982929c1938` | `99e30e3d709269915290355828f336179a1e5195b1cffb27fc07ad3fde5fe016` |
| `stage_center/news_link_projection.py` | `NEW` | `60a403924c9abcae050425f45ec55d7f84ff1fc99beb1403c2433994ec7e4611` |
| `apps/api/v35_api/app.py` | `b21a06958262f32715dafc8282e8ae292992c954c8ff0a7351f24d37bcb51a2b` | `eb9710e09ed500a1b01004512ae5fd14376c1a152a58dac693f9386ef7221279` |
| `apps/web/src/App.vue` | `1b48a1fe966f36adbb0ea71d9572bc8fcbeb3b441867da49c87547b236739dc6` | `030f0342269690ae12e7efb9d2e43cc14f607d2ede1565285a4974d0beca10c6` |
| `apps/web/src/app_shell/types.ts` | `789c67010b2b919061ff9d48f82fe7769c1e2e6dc08ddc19057c8d5e1afbd890` | `af426dc751a38a48c75c4216d6ba782f6244588c2aee00cc2bb4af5e2ede0c1f` |
| `apps/web/src/App.spec.ts` | `fa58941ab279b10f142d7785937d2b835d6386104e9c6af270470e347c35a1bb` | `5d0eefbf42e6efaf8e6834aab9abb22c0769421a90808436cd0ee710f3f2acc0` |
| `tests/test_news_link_projection_20261014.py` | `NEW` | `2a5284ad041c26c2ebf155244ce8f670372ff2b00d29d4e2412b1c597e1050fb` |
