# HK 09:35 admission gate diagnosis, 2026-10-14

Status: OFFLINE_COUNTERFACTUAL_ONLY / DIRECTION_ONLY. No selector/source changes, published result changes or service actions in this diagnosis. Rule decision pending user confirmation.
Source root: /Users/lexi/Desktop/学习/v4_app. Baseline commit 4786f4636cbec7ee5a5dec505c281cd76c615935.

Exact recorded D-1 Top100 raw SHA256: 35ad42ab3f8a30472daa282d073f54818d778e1c730cc79b68c806ff78192f54.
Pre-cutoff snapshot physical SHA256: 2d82150054c0cb6fa22ea25812ccaf5c58c4fcd738988ce89bc525cad7263d2b.
Full acquisition: 100; pre-capture positive: 40; positive plus HKD20m turnover: 4; plus volume ratio >=1: same 4.

The legacy live-gainer predicate exists in hk_active_snapshot.py and hk_minute.py. Selection_builder_registry.py restricts ordinary minute-stage rows to LIVE_HKCONNECT_GAINER before scoring and records inactive rows as missing. The original full D-1 pool is therefore acquired, but only four rows reach the stage scorer. Yesterday's recovered ten-row observation output used the explicit after-fact fallback and is not comparable natural-rule acceptance.

Frozen offline comparisons reuse today's immutable raw and snapshot, current four-lane scorer/sort, and no source calls. Baseline reproduced exactly: HK.02656=91, HK.09903=78, HK.02476=74, HK.06166=73.
1. Change only admission to include all 100 normalized rows: ten rows; original four remain ranks 1-4. Inactive rows currently lose captured volume_ratio, which suppresses their scores.
2. Separately restore the actual pre-cutoff volume_ratio for those rows (never fabricate live-gainer lane): same original four; added candidates below. This is a rule proposal and field-preservation diagnostic, not a performance validation.

| Name | Code | Score | Existing action classification |
|---|---|---:|---|
| 博泰车联 | HK.02889 | 66 | WATCH_ONLY |
| 布鲁可 | HK.00325 | 66 | WATCH_ONLY |
| 拓璞数控 | HK.07688 | 62 | WATCH_ONLY |
| 安德利果汁 | HK.02218 | 59 | NO_TRADE |
| 星源材质 | HK.06067 | 59 | NO_TRADE |
| 溜溜梅 | HK.06658 | 59 | NO_TRADE |

Proposed explicit decision: all valid exact D-1 Top100 rows enter stage ranking; original live-gainer predicate remains a truthful tag/score contribution rather than the exclusive admission condition; preserve captured quote fields for all rows; use the existing Top10 cap and show NO_TRADE/observation honestly. Missing means absent/invalid data, not failure of a strategy condition. Keep dates, cutoff/SHA checks, market separation and all trading gates unchanged. Do not rewrite natural history as if the new rule ran then.

Execution: existing v3.5-mac Python, PYTHONPATH canonical root, local `hk-gate-diagnosis/compare.py`. Initial diagnostic omitted turnover_hkd alias and failed baseline equality; corrected to match the actual builder, then exact four-code/score baseline passed. Two comparisons were saved separately. Independent Reviewer NOT_RUN per direct no-subagent instruction. No financial-return or natural-behavior acceptance claim.
Local reproducible script and machine result: /Users/lexi/Desktop/学习/agents调试/V4_NATURAL_MONITOR_20261014/hk-gate-diagnosis/compare.py and comparison.json. Raw data excluded from GitHub sync.
