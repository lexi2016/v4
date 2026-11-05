# Observation-date entry and existing US context

The user opened `workbench.html?date=2026-11-05`, but the entry parser treated every `date` as a source day. The owned catalog contained source 2026-11-04, observation 2026-11-05 and revision `e3ff25234adf18d8f29805a1107b36d61416b7bba3af8f3da9e63f17ee42fe09`; requesting `/days/2026-11-05` returned 404. The visible date control already used observation dates, so the URL and control disagreed.

The same page's cross-market card consumed a host binding containing only older static US/Japan entries. The stage-selection page already used the existing `/api/v4/research/us-market?research_date=20261105` API, which returned the saved 11/04 post-close capture, 13/24 usable boards and PARTIAL status. This change connects the workbench to that same API; it introduces no acquisition, producer, backend route or business-data write.

## Date compatibility

- Legacy `?date=D` keeps exact source-date priority. Only when that source is absent does it match the catalog's exact observation date. No previous-day arithmetic, weekend guess or latest fallback is used.
- A successful fixed binding normalizes the URL to `?source_date=S&observation_date=O`. Thus the user's 11/05 entry becomes source 11/04, observation 11/05 and cannot drift when a later source 11/05 appears.
- Explicit source/observation conflicts, unknown dates and multiple distinct sources for the same observation remain CANNOT_CONFIRM. Same-source versions retain the established R2 preference.
- Manual observation/source controls produce fixed URLs. Latest removes fixed date parameters and retains latest-follow intent. Completion-catalog responses check the captured intent and selection before applying, so a manual change invalidates a delayed response.

## Saved context and automatic-read boundary

The bootstrap requests the current day's existing context and the exact-observation `us-market` API independently. The US projection validates target aliases, schema, safety flags, source/session consistency, artifact/manifest/receipt references and board coverage. It preserves 13/24, PARTIAL, the source session and original `2026-11-04T21:15:02Z` capture time. An invalid or failed US response affects only the US card. Japan's missing daily source and Korea's `KR_PRICE_BASELINE_MISSING` remain visible from the existing context.

The existing context serial also invalidated an in-flight day-level read when same-day chart selection cleared/reused the context. A real-call-chain regression reproduced UNKNOWN instead of PARTIAL. Same-day chart clearing now preserves the day context, cache hits do not advance its serial, and day unbinding/source changes still invalidate it. Chart data, rendering rules and company request/error handling are unchanged.

Reads occur on entry/date selection, existing daily/context/observation completion notifications and returning focus/visibility. Concurrent foreground notifications share one in-flight refresh. There is no new interval, polling or capture event. A new US capture with no existing notification is read at the next listed trigger; this change does **not** claim that every capture immediately pushes a new SSE notification. The existing 30-second presentation-only clock is retained.

## Source and verification

Baseline: `863b9667798f3a5da33cab5d726ac47de52a8013`; branch `codex/observation-sync-20261105`. Seven allowed paths: four frontend modules (entry-date, shell, bootstrap and one US projection helper), two targeted JavaScript tests and this compact result. Entry-date and shell were absent from that source baseline and were first imported from exact current static bytes, before the bounded delta. The accepted bootstrap was the starting point; the canonical dirty workspace was not edited.

```sh
V4_US_CONTEXT_FIXTURE=/Users/lexi/Desktop/学习/agents调试/v4_observation_sync_20261105/US_MARKET_BEFORE.json \
node --test tests/test_workbench_entry_date.mjs tests/test_workbench_us_context.mjs
```

**11 tests passed**, with no skips. Tests execute the actual shell entry/control/catalog methods and bootstrap context/foreground/chart-clear functions against controlled DOM/network surfaces. They cover legacy compatibility, explicit-pair normalization, unknown/ambiguous/conflicting dates, delayed catalog/manual selection, later-source non-drift, Latest, the saved real US response, US failure isolation, delayed cross-day responses and foreground coalescing. Syntax checks passed for all four changed resources. `INFLIGHT_CONTEXT_REPRO_FAIL.txt` retains the same-day in-flight failure before its correction. Prior Python/material-content and company-error passes are reused; those inputs and code were not changed, and they were not rerun.

The APFS COW static candidate preserves every non-delta file SHA: 492 to 493 actual files and 489 to 490 allowlist entries. Four resources differ. The received-company module remains `9fdc1b943f2c207cf55f79b3f31226b66a04a0f716e2db93b1b84004933109c2`; natural-flow CSS remains `d033d27a23d72983fb6249b39c0a9ae2fee54966fb8a833840fabc592668434f`. The proposed API plist changes only the static root and asset-manifest environment values. API app/release/manifest and all business data remain untouched by the Writer.

Evidence root: `/Users/lexi/Desktop/学习/agents调试/v4_observation_sync_20261105/`. `ROOT_DIAGNOSIS.json`, saved history/context/US responses, `LIVE_SOURCE_BEFORE.json`, `EXACT_FRONTEND_DELTA.diff`, `CANDIDATE_STATIC_RECEIPT.json`, `API_STATIC_ONLY_CANDIDATE.plist` and `WRITER_HANDOFF.json` bind the reproduction and candidate. The 8911 preview serves only candidate static resources and proxies existing GET APIs to 8873; it creates no fixture or new data.

Independent review: **REVIEWED/PASS**, with the actual seven-file diff, 11 targeted tests, four module syntax checks, candidate/manifest mapping and current/stale response boundaries inspected. The Reviewer also confirmed that unbinding prevents pending old-day context replies from restoring content. The prior same-day in-flight FAIL and its correction remain recorded.

Root preview and actual live CUA: **UI_VERIFIED**. Reloading the user's existing 8873 tab from `?date=2026-11-05` normalized it to `?source_date=2026-11-04&observation_date=2026-11-05` and displayed 238 candidates. The US card used the same stage-selection API with 13/24, PARTIAL, session 20261104 and original capture time. Japan remained unbound; Korea retained its real missing-baseline error. The existing 300856.SZ received fundamentals and three-theme 3+3/strict-zero summary remained visible. No console errors were recorded, and GUI control was released.

Root activation/API: **DEPLOYED / API_VERIFIED**. Only the two static environment paths changed; PID 11086 replaced PID 9507, all four served resource SHA values matched the candidate, and the frontend was VERIFIED. API application/release/manifest and non-API plist bytes remained unchanged. Actual day and US GET checks confirmed source 11/04, observation 11/05, 238 rows and the existing exact-date PARTIAL capture.

The initial live reads queued while three same-origin workbench tabs were present. Root closed its old verification tab 8, after which reads completed; user tabs 1/2/3 were retained. The cause remains **CANNOT_CONFIRM**. No server fault or further source repair is claimed for that transient wait. `LIVE_API_QA.json`, `LIVE_UI_QA.json` and `ACTIVATION.json` retain the measured scope and timing.

Natural capture after deployment: **NOT_RUN**. CANNOT_CONFIRM remains for Japan's missing source, Korea's missing price baseline, immediate capture push without an existing notification, full board/company-relation coverage, financial full-content certification, historical PIT and complete B1 chain. A successful entry/API projection does not certify those layers. Source commit/push and exact seven-file remote readback are recorded separately in `GITHUB_SYNC.json`; no raw data, runtime files, plist, log or screenshot belongs to the source commit. Root authorized closing only this task's 8911 preview after live acceptance.

`RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.
