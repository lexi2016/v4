# HK 09:30–09:35 cached recovery — 2026-10-21

The stage had A10 but no HK output after the earlier READY-status rejection. This incident recovered only the missing HK lane using an existing immutable Futu K_1M/NONE cache. It did not query a provider, change a service, alter ranking, or modify A-share results.

## Result and independent acceptance

The existing source captured at 09:41:22.678854+08:00 contains 500 complete bars for 09:31–09:35 and exactly the frozen100 codes. The unchanged native collector/aggregator and selector consumed all100 and produced10 observation rows. The one-shot capsule was executed once after an independent PASS. The actual RawStore/SelectionStore trios, source data recomputation, owner bindings and real API were independently verified. A objects, pointers and six immutable file hashes remained identical. The reloaded V4 page shows this exact stage with A10 / HK10.

Nine focused tests passed, the independent native sandbox passed100->10, and six native dispatcher re-entry cases all skipped without work or writes. Actual execution delta received REVIEWED/PASS. The operator attempt is2, consumed, SETTLED_PARTIAL, with no pending execution or automatic retry. Do not run the capsule again.

The result remains PARTIAL_WITH_ROWS / OBSERVATION_UNVERIFIED / NO_TRADE / NO_BUY, with formal eligibility false. The historical 09:35 active snapshot and orderbook are unavailable. The 09:41 cache is after the requested window, so capture-time PIT, original natural execution and five-second timing are not verified. The aggregator's temporal_cutoff_safe=true concerns bar timestamps only; source/selection evidence says pit_safe=false and the owner explicitly records temporal_cutoff_safe=false. API execution_verified and natural_verified remain false. The recovery does not upgrade any formal/trading gate.

## Reproducibility and scope

Source root: `/Users/lexi/Desktop/学习/v4_app`.
Runtime: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-ready-status-20261021-r1/app`.
Interpreter: the existing service Python3.14 at `runtime/venvs/v3.5-mac/bin/python`.
Remote base: `f9154a3b4db1d7657ae6549f2efe41d6979b6caf`.
Work branch: `codex/hk-stage0930-recovery-20261021-r1`.

The four adjacent incident Python files are retained source, not a new producer or deployable service. Their input/config/A integrity pins and raw data remain local. `verify_isolated.py --out <fresh-directory>` reproduces the native path with local retained dependencies; `python -B -m pytest -q -p no:cacheprovider test_cached_recovery.py --basetemp=<fresh-directory>` runs the focused checks. Original local evidence root is `V4_HK_STAGE0930_RECOVERY_20261021_R1` under the user's agents调试 directory. Pins and dependencies are intentionally not shipped, and paths are incident-specific.

| Accepted evidence | SHA256 |
|---|---|
| cached_source.py | 12535e19705af301ca55db89d8381ed0a8d1352a4abb7e947b30040291d51ca6 |
| recover_hk_0930_reviewed.py | 4dcaeaccf3e057c98de77b492c540b3aaaf2e301641dd481a5152482198fabbc |
| verify_isolated.py | 753998e9791efc20f20c71e3f7e1834e15b2d9f82f4445f72d3ae4ad926fd11a |
| test_cached_recovery.py | c7014e25749dfc753632a3541b3d46a724db0bba295f7aceeee07cac60bd5d76 |
| independent_review.json (local) | 4402b0711e1b6d00407045ee312d37213ac5c28268edad5ce67f2e7a2ab427ae |
| actual_recovery_independent_review.json (local) | 06683a2346ba06ea542cbd6b34d2c0ef0eb3d824a37dc11103967c34aadcfd42 |
| source cache (local) | dc0c86f62e809713373ce20c1b6eb558474ff59b275290b8c4fed3dacee1ab41 |
| actual owner receipt (local) | feed64cb3b7df52eab8d39f8c1f56c96fd10f3f73120cf8e6b62593ea96ec450 |
| actual API response (local) | 106a8571397ce6133981d5655da7359f15f93eeb3499743c4c03ccf4ffbd5d5c |

This source branch also carries the previously accepted, previously unsynced READY validator and regression test unchanged. Before/after source SHA, prior runtime dependency and29-test independent acceptance are recorded in `../hk_ready_status_20261021/RESULT.md`. That earlier report is historical; this report closes its stage0930 gap. The earlier09:20 full100 observation gap remains outside this recovery.

Excluded from GitHub: credentials, raw captures, runtime/config/pins, A artifacts, logs, screenshots and complete API responses. Business source changes for this recovery: none. No service deployment, model change, provider acquisition, original-time recapture, or trading action was run. RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.
