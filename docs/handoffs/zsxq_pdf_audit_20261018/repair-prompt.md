# Chat repair prompt: ZSXQ PDF download-URL failures

GOAL: Diagnose and, only if a local response-contract defect is proven, make the smallest repair for the confirmed ZSXQ PDF URL-resolution failures. Keep the existing bounded queue and accepted long-PDF behavior.

EVIDENCE: The Oct 17 exact-date API/index has 558 source references: 427 READY, 131 FAILED, 0 pending. All 131 failed rows have `ZSXQ_DOWNLOAD_URL_MISSING`, `failure_class=TRANSIENT`, `attempts=2`; Oct 16 has 190 more failures with the same code after two attempts. The 106-page Oct 17 document completed through 53 two-page queue ticks; the 89-page document was reused from Oct 16 with 89/89 pages. Runtime/repository ingestion module SHA is the previously accepted `727a3f6cfcef626d6cf482eebf9e8d66418fcbe9817ae2e1dd1943c88e8384e0`. The raw upstream response is unavailable, so the underlying cause is CANNOT_CONFIRM.

INSPECT ONLY THESE CODE PATHS:
- `infrastructure/zsxq_pdf_ingestion.py`: `_cli_download_url` (the current error boundary), `_cli_json`, failure classification/retry eligibility, and the queue tick.
- `tests/test_zsxq_pdf_ingestion.py`: existing two-page continuation/backoff cases and add only a focused mocked response-contract regression if the defect is reproducible.
- `ops/run_zsxq_hourly_delta.py`: only the queue CLI seam if required to trace the response path.

WORK RULES: Do not call the live ZSXQ API, download PDFs, enqueue work, run OCR, or edit the shared runtime index. Do not use a guessed URL, a `source`/attachment field as a URL, or weaken HTTPS/userinfo validation. Do not increase `MAX_ATTEMPTS` or remove backoff without evidence. Preserve source run/date/file ID/hash bindings, existing page outputs, URL redaction, and the research-only safety flags. Keep the Oct 18 date-picker/UI behavior outside this repair.

PASS SIGNAL: Provide a deterministic mocked reproduction showing the actual supported response shape; if current parsing is wrong, patch only the parser and add tests for valid URL, missing URL, and unsafe URL responses. If the upstream fixture genuinely contains no URL, leave the failure explicit as `CANNOT_CONFIRM`, do not invent a fallback, and return the exact evidence needed for an authorized source-side recovery. In either case, focused tests must prove no URL or credential persists and the existing two-page continuation/backoff tests remain intact. Do not rerun the full prior 31-test suite or trigger any live queue work.
