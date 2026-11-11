# US benchmark dependency repair · 2026-11-11

## Goal and scope

Repair the existing 8873 workbench's three US index closes so they can be collected, validated, and displayed from their own exact-session Futu pages when the unrelated `external_finance` digest is missing. Session dates remain bound to the existing official US calendar; Futu code, title, quote, change, timezone, close time, and source-page checks remain strict. Failed or conflicting sources stay `CANNOT_CONFIRM`/`SOURCE_ERROR`; no previous session is substituted.

Writer branch: `codex/us-benchmark-dependency-fix-20261111` in `.task_worktrees/us-benchmark-dependency-fix-20261111`.

Allowed changes: observer collector, its US benchmark renderer, focused regression tests, and this record. Forbidden scope respected: active runtime files, API source/release, LaunchAgent, shared market data, A-share rows, models, and trading settings were not changed.

## Baseline and source identity

- Tracked baseline: `c9a46c1138eb212051be0160083ac84715c1c54c` (`codex/daily-market-chain-20261105`), clean when the task worktree was created.
- Active observer collector before this change and tracked baseline collector had the same SHA-256: `0a8a49ba0dce70d4aa15370fb17ed50db654491f05e74a13e49a4645973652da`.
- Active renderer before this change and tracked baseline renderer had the same SHA-256: `5234c29b465808c1ee89e96d8dd0641f28174bbb620e60326cfa7f2a0af7b862`.
- Active asset manifest before this change: `research-panel-assets.json`, SHA-256 `fc1d41562a5b5dde73ee89f2ad28db09f5943edcbbec369278cabaa2b40b8923`; its renderer entry used the same `5234c29b...` SHA. No newer renderer bytes were overlaid.
- Controller's baseline GET for `research_date=20261111` returned `CANNOT_CONFIRM`, `EXACT_EXTERNAL_FINANCE_NOT_MATERIALIZED`, empty session/rows, and null artifact/manifest/receipt. The controller's matching receipt and response evidence are in [BASELINE.json](/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/workbench_engineering_rectification_20261030/us_benchmark_dependency_fix_20261111/BASELINE.json).
- The source worktree does not contain `infrastructure/research_workbench_host.py`; the focused Python tests therefore use the existing observer app as `V4_OBSERVATION_OWNER_APP`. The new benchmark regressions use a small synthetic HTML response and need no external market-page fixtures. The saved official-page/JP fixtures remain optional for their existing source-specific tests.

## Change and current candidate hashes

- `ops/collect_workbench_observations.py` (`a156575144ada2c6d3bd3c6aabb06d38fafd090ca38e7c4d72d3524ecaa3364c`): session now comes from `latest_completed_session` and its official calendar receipt. The `/api/v4/research/us-market` call becomes optional sector context. Its missing, malformed, failed, or conflicting response is recorded under `market_context` diagnostics while the three Futu pages are still independently fetched and checked. Completed-session cache reuse now requires exact observation/session/close/calendar identity, receipt hash, and valid rows. Naive or invalid cache timestamps are cache misses and fall through to the exact-page fetch path.
- `research/stock_panel_collab_20261030/mac-host/workbench-us-context.mjs` (`64f67efaf8959362d15d878de2d3538454854a1393405b21ff10304282482fcb`): benchmark display binds to the observation, exact US session close, calendar reference, and raw receipt; it no longer requires the unrelated API artifact/manifest/receipt trio. Supplemental sector-board context keeps its separate exact API provenance checks.
- `tests/test_workbench_japan_observation.py` (`81996abb6ec063c0d9200fa38091b41023cc89e42c629fd699f697544b30f5e0`): missing, malformed, session-conflicting, and timeout API cases; wrong/stale Futu page rejection; exact calendar reuse for weekend, Thanksgiving closure, DST, and early close; valid completed-cache reuse; naive cached `read_at` triggers three exact page fetches and a dated result.
- `tests/test_workbench_us_context.mjs` (`18e9a8141ea1c4add23dfe6d528d1d29a8bf197c9833caef89527063fddcaa64`): verifies all three dated closes render without API receipts, while a stale row remains missing and invalid calendar/API context does not validate that supplemental context.

## Verification

The incremental cache regression ran with the active observer interpreter `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python`, `-B`, and `PYTHONDONTWRITEBYTECODE=1` to avoid writing bytecode into the runtime owner tree.

```sh
PYTHONDONTWRITEBYTECODE=1 V4_OBSERVATION_OWNER_APP='/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/v4-daily-market-chain-20261105-r1-observer/app' \
V4_MARKET_SOURCE_FIXTURES='/Users/lexi/Desktop/学习/agents调试/v4_market_readability_20261105' \
'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python' -B -m pytest -q --basetemp=/tmp/us-benchmark-cache-naive-20261111 tests/test_workbench_japan_observation.py
# 34 passed

env -u V4_MARKET_SOURCE_FIXTURES PYTHONDONTWRITEBYTECODE=1 \
V4_OBSERVATION_OWNER_APP='/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/v4-daily-market-chain-20261105-r1-observer/app' \
'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python' -B -m pytest -q --basetemp=/tmp/us-benchmark-cache-naive-synthetic-20261111 tests/test_workbench_japan_observation.py
# 19 passed, 15 skipped (only saved-source/Japan fixture-dependent cases)

node --test tests/test_workbench_us_context.mjs
# 13 passed before the cache-only delta; renderer and Node test hashes were frozen and unchanged.

git diff --check
# passed
```

The self-contained Python run executes the new benchmark regressions without `V4_MARKET_SOURCE_FIXTURES`. These tests still require the existing observer owner dependency root; with neither that root nor its dependency in the source tree, the module reports an explicit skip. The independent reviewer already passed the unchanged Node renderer suite (13 tests); it was not rerun for this cache-only delta. No live data capture was run by the Writer.

## Integration handoff

This candidate is not integrated, deployed, API-verified, UI-verified, or naturally verified. After the independent review:

1. In the controller-prepared versioned observer app, replace only `ops/collect_workbench_observations.py` with the reviewed candidate bytes and refresh the existing inventory identity. Keep the active API/source release, configuration, lock, 35-slot schedule, and services unchanged.
2. In the current static asset root `/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-v192-partial-20261110-r2/research-panel`, replace only `workbench-host/workbench-us-context.mjs` and update only its `files[]` SHA entry in the sibling `research-panel-assets.json`. Reload the existing API only as needed to refresh its in-memory asset allowlist; do not rebuild or replace the API release.
3. For a same-day US-context refresh, use the existing state root's `.capture.lock`: read and verify the exact current `latest.json` snapshot and matching source identity; preserve its A-share `rows`, Korea record, Japan record, and existing raw references; call only `us_benchmarks` with the real current clock and the prior same-day context; replace only `snapshot.context.us_benchmarks`; set the refreshed snapshot/receipt `recorded_at` from the actual completion clock; then call the existing `publish` path and update the existing slot pointer as required by that owner. This keeps actual Futu `read_at` times and new SHA-bound raw/receipt while avoiding a full 380-row `official_close` run or rewriting prior A/JP/KR data. Do not use `--manual-current` for this repair: the existing runner does not carry A rows into a new slot.

Controller must perform the resulting API/UI readback against the new receipt and separately report whether the exact-date market context is still unavailable. The controller-provided current transport probe was healthy, but it did not establish a newly materialized `external_finance` artifact or a live UI result.
