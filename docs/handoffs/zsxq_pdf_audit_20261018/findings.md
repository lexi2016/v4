# ZSXQ PDF recent-ingestion audit

Captured in Asia/Shanghai from 2026-10-18T00:23:15.246689+08:00 through 2026-10-18T00:23:15.309976+08:00. Source index last changed at 2026-10-17T23:17:04.572878+08:00 and SHA-256 `3f279b93b48c13ed32651292b7a72339f8a19712bae731de3277f924e1141239`. The index did not change during this audit. No PDF bytes, page text, credential material, live queue actions, OCR, or downloads were used.

## Result

**2026-10-17 is PARTIAL, not fully processed:** source folders enumerate 558 PDF references; all 558 reconcile to unique attachment IDs, unique source hashes, and index entries. The API and index agree on 427 READY and 131 FAILED, with 0 PARTIAL and 0 PENDING. All 131 failures have `ZSXQ_DOWNLOAD_URL_MISSING`, `failure_class=TRANSIENT`, and `attempts=2`.

**2026-10-18 is CANNOT_CONFIRM:** one exact-date API read returned `NOT_MATERIALIZED` / `NOT_ASSESSED` with `PDF_SOURCE_ENUMERATION_MISSING`; there were no 20261018 source folders or index source entries at capture. That is not evidence of zero new PDFs or a completed run. The host was shortly after midnight. The coordinator’s UI receipt records a date input capped at 2026-10-17 and the direct 20261018 URL rendering older exact source16; see `ui-evidence.json`.

Older backlog is separate: 2026-10-16 has 680 indexed PDFs, 490 READY and 190 FAILED, all with the same URL error after two attempts. The oldest unresolved Oct 16 failure was last updated at 2026-10-16T14:55:58+08:00; the oldest Oct 17 failure at 2026-10-17T10:20:01+08:00. The index records no PENDING items. The latest Oct 17 processing receipt is dated 23:17:04, with global totals 996 done, 321 failed, 0 pending. Subsequent scheduler queue log entries end with `NO_RETRYABLE_TASKS` / pending count 0. This means the retryable queue drained; the 321 failures remain unresolved.

## P0/P1/P2

- **P0: none observed.** LaunchAgent safety fields are `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false`; this is a research ingestion gap.
- **P1: 321 failed references across Oct 16–17.** Oct 17 is 23.5% failed (131/558); Oct 16 is 27.9% (190/680). Every failure shares the URL-resolution error, and attempts are exhausted. The persisted `failure_class=TRANSIENT` label does not make these retryable because the code caps attempts at 2.
- **P2: Oct 18 is not assessable yet; UI selection is capped at Oct 17.** The direct API response correctly reports missing source enumeration. The UI boundary makes the current date harder to inspect, but no date-picker repair is included in the frozen PDF audit.

## Long PDF continuation

For Oct 17, the 106-page document progressed in the scheduler queue from 2 through 106 processed pages over 53 queue ticks, with increments of 2 pages; it finished READY with 106/106 `OCR_OK` pages. The 89-page document was reused from the Oct 16 source run and is READY with 89/89 pages; its `ocr_completed_at` is Oct 16, confirming no repeat OCR in this run. The accepted long-PDF verdict file hash and active module SHA match the previously supplied evidence. The current 89-page attachment is a separate item reused from the Oct 16 08:30 source run; its SHA did not match the prior test target, so the older verdict is code-path evidence only. The current index and queue events independently prove 89/89 reuse. No full prior test suite was rerun.

The active scheduler process was LaunchAgent `com.lexi.v35.scheduler` (PID 60131, started Oct 16 12:39), with app root `zsxq-long-pdf-scheduler-20261016-r3`; the API process cwd was `us-receipt-compat-api-20261017-r1`. Scheduler logs contain repeated queue ticks and the final no-retryable state. The queue implementation bounds each document tick to two pages and applies a five-minute retry backoff.

## Root cause and test evidence

Observed code path: `_cli_download_url` requests `GET /v2/files/{file_id}/download_url` and raises `ZSXQ_DOWNLOAD_URL_MISSING` when `body.resp_data.download_url` is not a string. The failure code and exhausted-attempt metadata are directly observed. **CANNOT_CONFIRM** whether the upstream response omitted the field or the local parser does not match the actual response shape; the response itself is not persisted and was not requested in this audit.

Inspected focused tests in `tests/test_zsxq_pdf_ingestion.py`: two-page continuation beyond 128 pages, bounded queue progress, and transient retry/backoff. No test for `ZSXQ_DOWNLOAD_URL_MISSING` was found. Tests were not run in this read-only operational audit.

See [`audit.json`](audit.json) for the source signatures/input hashes, exact-date API counts, receipt/log hashes, runtime identity, and status tallies. A bounded Chat repair prompt is in [`repair-prompt.md`](repair-prompt.md).
