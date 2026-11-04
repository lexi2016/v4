# 首页日期与 A 股收盘复盘候选

Canonical project: `/Users/lexi/Desktop/学习/v4_app`. Isolated Writer tree:
`/Users/lexi/.codex/worktrees/ui-date-top200-20261104`, branch
`codex/ui-date-top200-20261104`. Repository base was `b4719b0f36fcaec237f34c88aaab56a6996a0296`.
The repository frontend lagged the verified active r3 source. Baseline-only
commits `105aec6cf`, `caedfd00a`, `aa9e8be0d` preserve its import closure,
multipage inputs and dependent fixtures; `baseline-files.json` records byte SHA.
These baseline changes are separate from the implementation diff.

## Behavior and scope

Root follows the date API's Shanghai `system_date` / `navigation_date`, even
without a materialized trading record. Routine navigation leaves `date` absent;
explicit history/deep links and next-day preparation keep their selected date.
“今日” clears the fixed date. Focus/pageshow/visibility restoration refreshes the
calendar only after initial navigation is ready and only in automatic mode.
The initial URL is captured before async calendar reads, so initial pageshow
cannot replace `view=a-top200` with stage navigation.

9A is an independent body, with a return to stage selection. It has readable
summary denominators, full 200-row lists in 50-row pages, union-hit filters,
pool/stage attribution, folded pool/stage statistics and folded raw evidence.
Missing requested dates never substitute another date; the recent-date button
is explicit. Data-ready scrolling puts the heading in view. Narrow-screen
horizontal scrolling is confined to the stock table.

The read-only mapper `ops/build_a_share_pool_top200.py` continues the existing
reviewed producer's output mapping. It never ranks or recalculates formulas.
It consumes saved Top200 rows and checks their artifact/package/input binding,
exact pool API fingerprint and each pool SHA, then reads only the stage CSVs
referenced by the original snapshot and verifies their SHA. It reconciles union,
per-pool and per-stage counts before adding memberships. Later stage reruns are
excluded. The original statistics and generated time remain unchanged.

11/04: 200 rows; whole pool 379 candidates / 24 hits; 5 of 7 stages,
45 candidates / 11 hits. Pools: 48/1, 40/1, 10/1, 314/24; two absent pools
retain null. All 24 union hits also belong to the research pool; overlapping
pool hits are never added together. 10/30: 200 rows; 531/49 whole pool,
29/7 stages. Dates 10/29, 11/02 and 11/03 lack matching saved detail and
remain `CANNOT_CONFIRM`; their existing aggregate statistics remain visible.

## Validation

- Date/navigation/App interaction: 7 targeted tests PASS, including initial
  pageshow/focus deep-link preservation and a nontrading system date.
- Panel/filter/pagination: 5 tests PASS; 200 ranks traverse four pages, 24 pool
  hits and 11 stage hits reconcile; missing date never silently falls back.
- HK observation-calendar: 1 existing test PASS. Timeline: 12 tests PASS
  (11 unchanged assertions plus the updated 9A-label assertion).
- Python mapper: 5 tests PASS, covering changed fingerprint/source/stage bytes,
  existing symbol forms, absent-stage isolation and delivered aggregate parity.
- `npm run build`: PASS. Exact test and build logs are in the local run directory.
- Full existing App suite has 11 failures reproduced in the r3 baseline; these
  unrelated behaviors were not changed. The relevant old 9A assertion was
  updated for the new body and is included in the seven targeted passes.
- Full `vue-tsc --noEmit` remains FAIL: 15 distinct existing diagnostic messages
  versus 18 on r3, with no new messages (`typecheck_comparison.json`). This is
  not a claim of full-repository type correctness.
- Controller CUA check: 638-wide and 1440-wide layouts had no page overflow;
  historical date, today, deep-link reload, stage filter and absent-date behavior
  were observed. Screenshots and detailed receipts remain in the local run dir.

## Candidate boundary

Inactive candidate preparation copies the verified current r3 application and
applies only six UI source files, the derived JSON in public/dist, the main
HTML and its required new assets. Secondary-page indexes and every non-delta
active byte remain preserved. The helper checks active plist/manifest SHA and
full inventory, including `entry_count`; it does not activate or edit launchd.
The repository's `read_active_release` rejects this V4 plist under its V35 role
contract (`API_RELEASE_ACTIVE_PLIST_ROLE_PATH_MISMATCH`); the existing r3 V4
helper's binding/inventory path is used, without changing that contract.

Run evidence and the final inactive candidate receipt:
`/Users/lexi/Desktop/学习/agents调试/v4_ui_date_top200_20261104/ui_repair/`.
Independent review, activation, runtime API/UI and natural verification are
separate controller stages. This Writer has not deployed or pushed.

`RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`,
`orders_sent=false`. No selection/rank rules, authoritative history, HK function,
Main/Stage service or Vibe 8910 change is included.
