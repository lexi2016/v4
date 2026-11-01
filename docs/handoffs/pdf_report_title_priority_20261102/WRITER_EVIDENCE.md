# PDF candidate metadata priority: writer evidence

Status: WRITER_TESTED_PENDING_INDEPENDENT_REVIEW. This is a candidate, not a deployment, API/UI acceptance, or historical-PIT certification.

- Baseline commit: `f71696f2f11d578e25ed8d3ee9f8015a57a16f70`.
- Active runtime observed during diagnosis: `edan-single-20261102-b843699e8d3371ea`; the candidate changes no running service or data.
- `infrastructure/zsxq_pdf_search_index.py`: baseline/runtime SHA-256 `5e7bdff17419ef688ab74cb66b1451c39cb201e3a64cfb9fca96db1cc5600f9a`; candidate SHA-256 `0c6e2494066bde53fd6285a4cfe7b2e84b2ff51a5357639b2bf1d7fded62f156`.
- The runtime owner module differs from the baseline worktree owner module. The candidate does not alter the owner and the real-data canary imported the runtime owner.

## Behavior and scope

Existing Bloom candidates with a full eligible search term in the owner title or filename sort first. Other candidates passing the existing full-name Bloom filter sort ahead of code-only candidates; date and document ID remain the stable tie-breakers. Names considered for priority contain at least two CJK characters or three ASCII letters; short numeric and market-code fragments do not gain name priority. Excluded short terms remain searchable by the unchanged Bloom filter. These are ordering hints only: original owner verification, source evidence matching, PDF-hash deduplication, and incomplete coverage semantics remain in the original relation reader. The candidate ordering version participates in the checkpoint so both earlier sorting versions' cursors fail stale.

For `002865.SZ`, the live baseline index placed two records for the same verified PDF at positions 635 and 981 of 2,560; the live relation API inspected only the first five and returned no match. An isolated in-process query using the candidate index code and the running release's original owner and relation reader returned the verified PDF in the first five, with both sources deduplicated by PDF SHA-256 `c5b33cdb8906e09bbd99b99ee101df9cd646e5a53efb183c1dd6662f68e1b3ed`. For `300206.SZ`, the same canary returned a previously verified body mention, SHA-256 `c9e5134da0853daed4b39ae2ef747c36e6b623030bcbbe40eb8be72bab7a2870`, among 3,964 candidates. Each query attempted and verified five documents, returned a continuation cursor, and remained `PARTIAL`; a body mention is not a confirmed report subject.

## Checks

- Project interpreter: `/Users/lexi/Desktop/学习/runtime/venvs/v3.5-mac/bin/python`.
- `PYTHONDONTWRITEBYTECODE=1 <interpreter> -m pytest -q -p no:cacheprovider --basetemp=<task-specific-temp> tests/test_pdf_report_title_priority.py tests/test_pdf_search_index.py`: **10 passed**.
- An isolated pytest run injected the running release's original PDF owner together with the candidate index module and ran `tests/test_related_pdf_reports.py`, `tests/test_pdf_search_index.py`, and `tests/test_pdf_report_title_priority.py`: **18 passed, 12 subtests passed**.
- Before the name-priority addition, the targeted regression was **3 failed, 3 passed**, covering body-name priority, short-term noise, and rejection of the prior priority version's cursor.
- `git diff --check`: passed.

The indexed library had 5,812 indexed and 1,506 unavailable documents, including 23 large pending; its historical coverage was not complete. The ordering does not bring all body-only mentions to the first page. `301048.SZ` no-match evidence and `300206.SZ` body mentions retain their separate diagnostic coverage limits. No index update, OCR, download, activation, or production/trading action was performed.
