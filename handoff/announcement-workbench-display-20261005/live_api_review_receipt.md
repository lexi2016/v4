# Independent live announcement API readback

**Checked:** 2026-10-05 09:28:54 UTC  
**Scope:** read-only GET verification against the actual service at `127.0.0.1:8873`. No service control, state writes, or non-GET requests were performed.

**Verdict:** `BEHAVIOR_VERIFIED: PASS` for the tested live API behavior: default target date `20260930` resolves to its expected publication date and verified product, while missing target date `20260928` stays explicitly `NOT_RUN`/`NOT_IMPORTED` with no reused `20260930` product. This is API-layer evidence only.

## Runtime and safety evidence

- `lsof -nP -iTCP:8873 -sTCP:LISTEN` found exactly one listener, PID `25120`, bound to `127.0.0.1:8873`. Its cwd is `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-announcement-r14-20261005-page-results-r1/app`.
- `GET /healthz` returned HTTP 200, `{"status":"ok"}`. `GET /readyz` returned HTTP 200 with `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false`.
- `GET /api/v1/runs/date-list?date=20260930` returned release identity `manager-announcement-r14-20261005-page-results-r1`, status `MANIFEST_EXECUTION_FILES_VERIFIED`, and manifest SHA-256 `220406155fc7b556cca64e8ec376abbbf88bc2f499a174905d1503ebbd783fc1`, matching the deployment receipt. Its `process_status` is `CANNOT_CONFIRM`; this review does not upgrade that field. The announcement API responses report `RESEARCH_ONLY=true` and the same three safe flags.

## Default `20260930` readback

`GET /api/v4/manager/research/announcements/analysis?date=20260930` (no `publication_date`) returned HTTP 200. The target is `20260930`, the default publication date is `2026-09-29`, and the selection basis is `PREVIOUS_HK_TRADING_SESSION`.

`source_catalog` is `COMPLETE` with `readback_status=VERIFIED`, run ID `f42f992f8705491492d065673bde9e9e`, 744 directory records across 39 pages, 234 manager announcements across 140 issuers, and no catalog gaps. `analysis.status=VERIFIED`; the response contains 234 records and summary counts of 207 complete API bodies, 22 long-PDF focus reads, and 5 text-insufficient/unassessed items. Product SHA-256 is `84090d130d1e19f714c8c0d63340e5eaae00f2506d5885af5afd385a3bc64486`, matching the deployment receipt.

The response leaves `point_in_time_status=CANNOT_CONFIRM`; `hkex_first_publication_verified=false` and `is_hkex_complete_directory=false`. The observed catalog is the declared Eastmoney HK date-scoped listing mirror, not proof of a complete HKEX directory or PIT-safe interpretation.

## Missing `20260928` readback and date isolation

`GET /api/v4/manager/research/announcements/analysis?date=20260928` (no `publication_date`) returned HTTP 200 for target `20260928`, selecting publication date `2026-09-25` by `PREVIOUS_HK_TRADING_SESSION`. The catalog is `NOT_RUN`, its readback is `NOT_RUN`, and its gap is `ANNOUNCEMENT_DATE_CATALOG_NOT_RUN`; analysis is `NOT_IMPORTED`, `summary` is empty, and product SHA is absent. The API returned an empty records array, which is a missing-prerequisite state, not evidence of zero announcements. No `20260930` product hash or 234-record summary appears in this response. `point_in_time_status=CANNOT_CONFIRM`.

**Evidence boundary:** these GETs independently verify the API response and active release identity. They do not independently verify browser/UI behavior or a natural scheduled run; those remain separate evidence layers.
