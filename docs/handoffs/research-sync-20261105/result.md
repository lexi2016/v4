# Received research in the existing workbench

The 2026-11-04 numeric product already contains the exact Futu115 four-group union of 238 symbols. Its company-material index had no entry for that date, so the workbench could not show the received company research or the 2026-11-05 secondary screen. The adapter projects only those 238 received rows into the existing company-material schema; the existing company endpoint and host projection remain unchanged.

The existing company sections now show source and observation dates, three research themes, three technical observations, three waiting-for-trigger names, received company text, canonical source-day performance, source links and missing evidence. The full-chain certified count remains zero. Original producer statuses remain 232 COMPLETED and 6 PARTIAL self reports; 13 companies have separately documented checks of specified official pages. Neither status becomes full financial or historical PIT certification.

The canonical attachment is explicitly the 2026-11-04 close, with the 2026-11-05 intraday return still null. Canonical current-five volume and external P5 current-five/previous-five references are separately labeled. Fifteen P5 close conflicts and one missing P5 feature/plan are preserved; their display reference fields are null. The original conflicted P5 records remain in evidence details. Narrative financial text is never parsed into numerical financial facts.

The existing daily completion callback refreshed list/statistics but did not reload the currently selected company's materials. A bounded bootstrap hook now uses that completion event to GET only the matching current company and reuses company-local request tickets. Responses from an older stock/day or an intervening same-symbol request cannot replace current content. There is no added timer or polling.

Independent review found one P2 failure path: a failed completion GET invalidated the old company request but left LOADING or old READY material visible. The targeted regression first reproduced `LOADING != ERROR`. The refresh now calls the existing ERROR status renderer for the still-current request, clearing the affected material; stale failures leave the newer stock/day untouched. A missing received payload also becomes a current-request error.

## Frozen source and runtime boundaries

- Source branch: `codex/research-sync-20261105`, baseline `cbd7771aae84c99f2394b10624cde5365f496230`.
- The baseline lacked the active mac-host bootstrap. Its exact live bytes (SHA256 `4c27333f65b37c4cd4bf81b8356930a27dd8ac8091164fac869b6caa1440a553`) were brought in before the small hook/import delta. An older worktree bootstrap was not used.
- Changes are limited to the importer, bootstrap, received-render module, two targeted tests and this result.
- Publication reuses the explicitly pinned `sync_stock_history_completion.publish` adapter and original daily-product `save`, including the shared A_LONG inode lock, expected index/event CAS, immutable references and existing completion event. Its inherited publication receipt type is `PUBLISHED_HISTORY_SYNC`; this import performs no historical computation.
- Only `company_materials[source_date]`, the completion event's material reference and event ID change on publication. Numeric manifests/artifacts, chart metadata, Top200, other dates, selection rules, ordering and BUY gates remain unchanged.
- No host/router/API contract, Main, Stage, Apre, reviewdaily, Vibe8910, scheduled task or trading change.

## Targeted verification

Environment: `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python -B`, Node's built-in test runner; no added dependency.

```sh
V4_EXISTING_PUBLICATION_ADAPTER=/Users/lexi/Desktop/学习/v4_app/.task_worktrees/stock-history-catchup-20261030/ops/sync_stock_history_completion.py \
PYTHONDONTWRITEBYTECODE=1 \
'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B -m pytest -q \
 tests/test_received_company_materials.py \
 --basetemp /Users/lexi/Desktop/学习/agents调试/v4_research_sync_20261105/pytest_final

V4_RECEIVED_STAGE=/Users/lexi/Desktop/学习/agents调试/v4_research_sync_20261105/stage \
node --test tests/test_received_research_ui.mjs
```

- Python: **12 passed**, covering exact scope, duplicate/extra/missing rejection, source/date/safety drift, null preservation, non-target index/event preservation, actual existing publisher success, index/event CAS and stable-lock drift rejection. The owner adapter is an explicit read-only local dependency, and the tests require that environment binding to run its four publication cases.
- JavaScript: **4 passed**, including all 238 staged records, 15+1 quarantine checks, three rendered representatives (300149.SZ, 300856.SZ, 688111.SH), safe text/URL rendering and delayed-response request-ticket rejection.
- P2 repair: **1 new targeted regression passed**, using the unchanged real `company-local.mjs` ticket and status functions. It covers LOADING/READY crossed with fetch failure, identity-validation failure and missing received payload, plus stale failures after stock/day/away-and-back selection. The previous Python 12 and JavaScript 4 passes are reused because their inputs and applicable behavior did not change.

```sh
V4_COMPANY_LOCAL_MODULE='/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-research-sync-20261105-r1/research-panel/workbench-host/company-local.mjs' \
node --test --test-name-pattern='current refresh failures' tests/test_received_research_ui.mjs
```

- Bootstrap and module syntax checks passed.
- All 238 staged shards were read through the actual installed `ResearchLaneSource.read_a_daily_company_materials` and projected through `ResearchWorkbenchHost.company`, with only reference resolution redirected to staging. This is stage validation, not live API acceptance.
- Preview HTTP: three representative company responses and four static assets passed; wrong revision was rejected. This is not browser acceptance.
- Initial pytest touched the shared pytest retention mechanism and encountered an unrelated existing EPERM cleanup error. No unrelated temporary content was changed; subsequent checks used this task's isolated basetemp. One test fixture initially lacked the existing owner's `immutable` keyword and was corrected; the real owner already supports it.

## Prepared artifacts and remaining gates

Local evidence root: `/Users/lexi/Desktop/学习/agents调试/v4_research_sync_20261105/`.

- `IMPORT_CONFIG.json`: pinned source/owner/adapter references.
- `stage/PUBLICATION_PLAN.json`: 238 shards plus one material index, staged index/event, exact before references and owner lock identity. Root published this exact plan after independent R2 acceptance; the Writer did not publish business data.
- `STAGED_EXISTING_READER_HOST_CHECK.json`, `PREVIEW_RECEIPT.json`, `FAILURE_NOTES.json` and `CANDIDATE_STATIC_RECEIPT.json`: scoped evidence.
- Static candidate: `v4-research-sync-20261105-r2/research-panel`, APFS COW clone preserving R1 and the exact current static source; only the bootstrap and new received module differ. All other 490 original file bytes are preserved, including black-area natural-flow CSS SHA256 `d033d27a23d72983fb6249b39c0a9ae2fee54966fb8a833840fabc592668434f`.
- `API_STATIC_ONLY_CANDIDATE.plist`: Root activated R2 by changing only the static root and asset-manifest environment values. API app/release/manifest and non-API plist bytes remain unchanged. The new API process is PID 9507; the prior PID 99025 exited. Served bootstrap/module SHA values match R2.
- The temporary 8909 preview used stage company payloads and proxied other APIs to 8873 with explicit stage response headers. Root's R1 CUA checked the three representatives and natural/narrow layout. It registered no production route and was not API acceptance. Root authorized closing this task's preview after the live checks.
- `REVIEW_R1_REPRO_FAILURE.txt`, `REVIEW_R1_TARGETED_REGRESSION.txt` and `REVIEW_R1_FIX_RECEIPT.json` preserve the P2 failure and targeted correction. R1 candidate/receipt/handoff bytes are retained. The 238-data plan and import config are reused without rewriting.

Independent Reviewer R1: **FAIL on the P2 above, retained**. Independent R2: **REVIEWED/PASS** for the corrected current/stale failure path and direct wiring/candidate changes, reusing the matching prior checks. Root publication: **PUBLISHED exact238**, with non-target index/event fields and numeric products preserved. Root activation and actual API: **API_VERIFIED**, including three representative company GETs (300149.SZ, 300856.SZ, 688111.SH); target-day returns remained null. Actual live CUA: **UI_VERIFIED_REPRESENTATIVE**, on 300856.SZ, showing the three themes, 238 original scope, 3+3 roles, zero full-chain certifications, received fundamentals and the 11/04 close performance (+1.14%; P5 current-five .9432 versus previous-five 1.0823). The natural-flow CSS remains intact, with no console errors or horizontal overflow in the recorded live viewport. Root released GUI control.

The first live 300149.SZ check timed out waiting for LOADING/summary. Root retained that failure, closed its previous verification tab, then selected 300856.SZ and obtained the correct live rendering. The cause remains **CANNOT_CONFIRM**; connection occupancy is only suspected. No additional source change was made for that observation. Preview CUA covered the three representatives; live CUA sampled one and does not certify every stock's rendered content.

This round's natural job verification: **NOT_RUN**. CANNOT_CONFIRM: full financial-content coverage, historical PIT, complete B1 chain, historical turnover, current market-cap/valuation binding and target-day intraday performance. Source commit/push and six-file remote readback are recorded separately in `GITHUB_SYNC.json`; no raw research data, runtime files, plist, logs or screenshot are included in the source commit.

Rollback is limited to restoring the prior static environment paths and the exact previous material index/event references under the same original-owner lock/CAS discipline; never reset numerical products or another owner's later changes. Successful original inputs and required evidence remain preserved.

`RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.
