# Workbench source-date close reference

Candidate repair for the list and selected header showing `—` while the next
observation session has no committed snapshot. Source branch:
`codex/workbench-source-close-quote-20261105`; Git baseline:
`1d8a0bc957eb2482a1d45a324311535398db0a8c`.

`ResearchWorkbenchHost.day` now includes a separate `source_close_reference`.
The read-only adapter follows the product's exact snapshot directory to its
accepted stage receipt and selector. It validates date, generation, input,
snapshot SHA, accepted selector SHA and Parquet contract; then reads only the
five required columns for that date and frozen candidate scope. It performs one
streaming source SHA check per source/file-stat identity and caches the small
projection. It never computes history or creates a producer, persistent store,
schedule, acquisition or company/Chat dependency. Any failed binding leaves the
reference `CANNOT_CONFIRM`, without blocking the existing day response.

The UI retains the original observation validity checks and prefers a valid
observation row. When none of that row's price/percent/amount fields is valid,
it may show the separately validated source-date close reference, with an
explicit date and `收盘参考` label. A partially valid observation keeps its
missing fields unknown. Close references never enter intraday `rowValidity`,
never invent `source_asof`, and never supply cumulative-volume ranking.
Price/percent/amount sorting places valid observation values before valid close
references, then unknown values; numerical ordering is only within each role.
Original groups, candidate scope, D2/D5 sorting and history remain unchanged.
Source-date and generation changes continue through the existing list/versions
completion path. No new polling is added.

The baseline lacks the active `research_workbench_host.py` and
`observation-local.mjs`. Their exact active files were imported before the narrow
patch. `SOURCE_ORIGINS.json` in the local evidence directory records origin
paths, before SHA and baseline SHA. The workbench shell already matched the
active static file. No other current runtime files were changed.

Validation environment: existing V4 interpreter
`/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python`;
Node `v24.19.0`; existing Playwright package with installed Chrome in headless
mode. No browser installation or user browser control occurred.

Commands and results:

- `python -B -m unittest tests.test_workbench_quote_reference -v`: 4 PASS.
- `WORKBENCH_STATIC_ROOT=<active research-panel> node --test tests/test_workbench_quote_reference_ui.mjs`: 5 PASS.
- `node --check` on both changed MJS files: PASS.
- Actual candidate host with current checked binding: 364/364 same-date references;
  removing the new field yields an exactly equal prior day JSON, including
  all group/history/classification fields; observations remain exactly equal.
- Headless same-entrypoint page with two candidate assets and candidate day
  response routed only in its own context: 000410.SZ, 603007.SH, 920007.BJ PASS;
  company API forced to 503 proves independence; no page errors; browser closed.

Bound source: date `20261105`, generation
`63986092da44625a69d34f5f98a300c8ba685ea023dbaa007639207caa3ea109`,
input SHA `6d3d3905293d44e5d4261f7cef1d7d3af3c2530ea10b381b428e3591fcb12854`,
selector SHA `0765424ddb7630fd5869ea344ad0621922145dc0f3db9fe7c1bb90f4a8826ba2`.
000410.SZ displays 5.46 yuan, +0.18%, 5.29 hundred-million yuan, dated 11/05;
observation day 11/06 remains unbound. No future return is filled.

Local evidence (not uploaded):
`/Users/lexi/Desktop/学习/agents调试/v4_workbench_quote_blanks_20261105/`:
`INITIAL_API_REPRO.json`, `SOURCE_ORIGINS.json`, `ACTUAL_HOST_VERIFICATION.json`,
`HEADLESS_CANDIDATE_VERIFICATION.json`, `CANDIDATE_000410.png`.
Initial test-fixture setup and an unqualified re-export symbol were corrected
before PASS. The bundled Playwright Chromium binary was absent; its failure
receipt was preserved, and installed Chrome was used successfully.

Status: source and candidate validation only. Independent review, deployment,
live API/UI and natural daily completion verification remain outside this Writer
handoff. User-tab visual verification is `CANNOT_CONFIRM`. All financial flags
remain `RESEARCH_ONLY=true`, `production_allowed=false`,
`buy_gate_updated=false`, `orders_sent=false`.
