# PDF cache metadata fix

Verified cached pages previously reached READY while leaving processed_page_count unset and full_page_coverage false. The cache-reuse branch now writes both fields after existing integrity and full-page checks succeed. No downloader, OCR, retry, or authorization behavior changed.

Only the ingestion source and its existing regression test changed. The regression failed before the fix; Writer ran 42 ingestion tests. An independent Reviewer reran three focused tests and two damaged/incomplete-cache exercises, which failed closed without URL/download/OCR calls.

The five previously recovered documents were corrected from their verified 26 cached pages without OCR/download. Original receipts were archived by SHA; an additive correction receipt links old/new hashes. Audit and claim bytes were independently confirmed unchanged. Five live detail GETs and the reloaded UI show all pages correctly. The whole index continued changing with the normal queue, so cross-time whole-index equality is not claimed.

The actual scheduler received only the same two assignments in a new immutable release. Independent verification matched all 855 inventory entries in both releases, with one file changed, and confirmed the active process/CWD, manifest and launch pointers. The API is a read-only consumer and was not modified or restarted. A new natural slot was not observed. Historical backlog recovery is a subsequent operational stage; raw data, runtime trees, and execution logs are excluded from this source handoff.

See manifest.json for baseline, before/after source hashes, exact runtime identity, independent receipt hashes, and evidence limits. The remote branch is a bounded source handoff; do not deploy its entire old base tree over the active application.
