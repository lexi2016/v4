# PDF candidate metadata priority: writer evidence

Status: WRITER_TESTED_PENDING_INDEPENDENT_REVIEW. This is a candidate, not a deployment, API/UI acceptance, or historical-PIT certification.

- Baseline commit: `f71696f2f11d578e25ed8d3ee9f8015a57a16f70`.
- Active runtime observed during diagnosis: `edan-single-20261102-b843699e8d3371ea`; the candidate changes no running service or data.
- `infrastructure/zsxq_pdf_search_index.py`: baseline/runtime SHA-256 `5e7bdff17419ef688ab74cb66b1451c39cb201e3a64cfb9fca96db1cc5600f9a`; candidate SHA-256 `65144b8fa5b0cc1a223139b9c755883d75d63c31f630af143b640b2346e36b81`.
- The runtime owner module differs from the baseline worktree owner module. The candidate does not alter the owner and the real-data canary imported the runtime owner.

## Behavior and scope

Existing Bloom candidates with a full eligible search term in the owner title or filename sort before other candidates; date and document ID remain the stable tie-breakers. Short numeric and short ASCII search fragments do not gain priority. A title hit is an ordering hint only: original owner verification, source evidence matching, PDF-hash deduplication, and incomplete coverage semantics remain in the original relation reader. The candidate ordering version participates in the checkpoint so pre-change cursors fail stale.

For `002865.SZ`, the live baseline index placed two records for the same verified PDF at positions 635 and 981 of 2,560; the live relation API inspected only the first five and returned no match. An isolated in-process query using the candidate index code and the running release's original owner and relation reader returned the verified PDF in the first five, with both sources deduplicated by PDF SHA-256 `c5b33cdb8906e09bbd99b99ee101df9cd646e5a53efb183c1dd6662f68e1b3ed`. It attempted and verified five documents, returned a continuation cursor, and remained `PARTIAL`.

## Checks

- Project interpreter: `/Users/lexi/Desktop/学习/runtime/venvs/v3.5-mac/bin/python`.
- `PYTHONDONTWRITEBYTECODE=1 <interpreter> -m pytest -q -p no:cacheprovider --basetemp=<task-specific-temp> tests/test_pdf_report_title_priority.py tests/test_pdf_search_index.py`: **8 passed**.
- An isolated pytest run injected the running release's original PDF owner together with the candidate index module and ran `tests/test_related_pdf_reports.py`, `tests/test_pdf_search_index.py`, and `tests/test_pdf_report_title_priority.py`: **16 passed, 12 subtests passed**.
- The pre-change targeted regression was **3 failed, 1 passed**, covering the missed first page and legacy cursor reuse. A later test-expectation correction retained date-descending order among prioritized records.
- `git diff --check`: passed.

The indexed library had 5,812 indexed and 1,506 unavailable documents, including 23 large pending; its historical coverage was not complete. This metadata-only priority does not bring all body-only mentions to the first page. `301048.SZ` no-match evidence and `300206.SZ` body mentions retain their separate diagnostic coverage limits. No index update, OCR, download, activation, or production/trading action was performed.
