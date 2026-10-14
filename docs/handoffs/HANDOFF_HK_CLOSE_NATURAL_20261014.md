# 20261014 16:10 close-time repair verification

Canonical source `/Users/lexi/Desktop/学习/v4_app`. Main assistant direct per user; no subagents. Previous handoff `HANDOFF_HK_CLOSE_TIME_REPAIR_20261013.md`. GitHub baseline `e7c344b93ce2d315dd60e68150772ea6e1728b28`.

## Natural result and first break

**NATURAL_VERIFIED applies to the close-time capture repair only.** Existing com.lexi.v35.scheduler naturally ran 1610 on 20261014, attempt 1, LIVE, catchup=false/lag=0, SUCCEEDED. Run `4f2b02a075724a929357749624e2a995`, finished `2026-10-14T08:10:16.784510Z`. Natural dispatcher SHA `779c4b66c743d14d9fab87136d039852d2fd446699ac5bc763d56b14e3f64955` remains byte-identical after this work.

Futu query time `2026-10-14T16:10:15+08:00`; all 698 rows same-day and verified by existing CloseSnapshotStore. Raw price update range `13:37:44–16:08:32`, preserved exactly in original update_time and timezone-normalized source_update_time. Snapshot SHA `00200c692080ea10850944d5c47b9f6c2db1fc0d1003cbba7391a4f1b0730a44`; provider-input SHA `9a8332852cb51920c311e778c6610a6824bee736b6de17051fe09ea772aed7de`. Actual natural scheduler retained the previous corrected collector/store SHA values from the 20261013 handoff.

Natural review artifact SHA `48f3945b6a2c9aab1bb049ac4f2a0c50b1b6812960fd36c5e99262eb4422365e`: Top20=20 and model candidates=100, but stage observations only10 from auction. First real break: actual scheduler's old monolithic SelectionStore raised `SelectionError: selection algorithm SHA mismatch` for current six-stage artifacts. Correct selection root was already bound. This was reader deployment compatibility, not missing source rows or failed close capture.

## Minimal recovery and deployment

Canonical source already supports the approved full-D1 algorithm; no canonical business-code change. Clone actual parent `morning-pools-20261014-r1-us-factor-r3`, preserve its other modifications, and add only the existing `HK_FULL_POOL_ALGORITHM_MANIFEST/SHA256` definition and that SHA to its monolithic reader ALGORITHM_SHA_ALLOWLIST. Approved identity `f2991c472b17742acfd3adb81458ff13826f99dfb7b8a223ad8d6a5dfbbd1a1e`; no scoring implementation, input producer, market-data cutoff, PIT gate or trading change.

Runtime stage_center/selection.py SHA before `6357a7be65574e54e82f770b2d297668c4b47646c3c0d6e3225039608475a005`; after `daaecfd554af6052c85331bf47f4e9605b29f291ccddcf8c930e8c362bcddda7`. Candidate import and real verified selection trios read all seven stages, ten rows each; unknown algorithm hash remains outside the allowlist. Canonical current `tests/test_close_review_producer.py` copied to isolated evidence path and run with candidate PYTHONPATH using v4 runtime v3.5-mac Python: `-B -m pytest -q <test copy> -k 'cached_close_snapshot or futu_collector' --basetemp=<isolated directory>`: **7 passed, 10 deselected**. An initial test copy came from the older runtime tests (1 passed,6 deselected); corrected to canonical absolute source before the final seven-test run.

Original `python -B -m ops.build_close_review --data-root <existing v35 state/data> --date 20261014 --stage-selection-root <existing v4 state/stage/selection>` rebuilt from existing verified snapshot and stage trios, with **no provider call**. Prior review/receipt saved locally; new review SHA `99e58cde4f85cce5052ac3f40584b6a926fa8c40d5f3cd20b50c574efa2ed533`. This rebuild is **MANUAL_RECOVERY**, not natural completion. Natural dispatcher payload retained its original review and was not rewritten.

New scheduler release `hk-close-reader-20261014-r1` under Application Support; manifest `335d368cedcd6829b00532587e81708d3ced0c9fe770883547564629dd30b327`; activated `2026-10-14T16:48:44.172796+08:00`. Waited for existing FUPAN_REVIEW_START child to finish before reload. Initial activation validation called a helper absent from the old package and stopped before mutation; replaced with actual package import/allowlist validation. launchd bootstrap initially returned exit5; old service restored, then bounded delayed retry succeeded. Readback PID3942 and DAEMON_READY confirm new release running. The subsequent 1555 catchup reports existing A-pool `RANK_FOR_REVIEW_ONLY_NOT_BUY_PRIORITY`, with no workload started; this separate backlog was preserved and not expanded into this repair.

## API and refreshed UI

8873 `/api/v3/review?date=20261014` and fresh browser click on the 16:10 close entry show Top20=20, HK universe=698, model candidates=100, stage observations=70, seven stages/27 unique codes. Model candidate overlap9/20; partial research observation overlap7/20. These overlaps are descriptive only. UI explicitly shows PIT未验证/NO_BUY and formal seven-stage union unavailable.

Remaining genuine gaps: UNVERIFIED_STAGE:STAGE_0940_0945; FUTU_AFTERFACT_CAPTURE_NOT_PIT_SAFE; HK_HISTORICAL_ORDERBOOK_UNAVAILABLE; HK_MODEL_SOURCE_PIT_AVAILABILITY_CANNOT_CONFIRM. Status remains MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE. Do not upgrade those gaps or this manual recovery to full natural semantic acceptance.

DEPLOYED / API_VERIFIED / UI_VERIFIED; main-agent checks passed. Independent REVIEWED / TESTED / BEHAVIOR_VERIFIED NOT_RUN per explicit no-subagent instruction. Full repaired review future natural slot remains NATURAL_SLOT_UNVERIFIED. Close-time capture itself NATURAL_VERIFIED as scoped above.

Local evidence `/Users/lexi/Desktop/学习/agents调试/V4_HK_CLOSE_NATURAL_20261014`: natural-dispatch.json, before-review copies, reader-verification.json, manual-rebuild.json, api-before/after (before is api.json), ui.txt, prepared/activation/daemon-readback/summary JSONs. No raw quotes, full responses or runtime packages uploaded. Only this condensed handoff is newly synced; approved identity already exists in baseline canonical source.

Single-check automation automation-3 deleted after completion. Research-only; production_allowed=false, buy_gate_updated=false, orders_sent=false. 8910 unchanged.
