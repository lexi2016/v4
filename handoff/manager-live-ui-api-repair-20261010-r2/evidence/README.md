# Evidence reading order

1. `RESULTS.json`: final status by candidate, review, isolated integration, full-project tests/build, deployment, live API/UI and natural session.
2. `final-validation.md` / `.json`: actual final paired populations, every failure and delta identity, commands, runtime and source SHA. Full test logs/XML/JSON remain local and are indexed by path/size/SHA; large raw output is not reuploaded.
3. `final-whole-change-review.md` / `.json`: final independent verdict on the frozen9-source proposal. It preserves all broad-suite failures and acceptance exclusions.
4. `backend-implementation.md`, `backend-independent-review.md`, `frontend-independent-review.md`: task-level reasoning and original review findings, including the resolved materialized-catalyst P2 and source-root-label P3.
5. `frontend-implementation-earlier.md`: point-in-time implementation report. Its71-case/5DTO count and pre-copy-label SHA table predate root's final P3 label correction and sixth actual DTO test. Final `SOURCE_MANIFEST.json`, final44/6 test results and whole-change review supersede those specific fields; the report is retained for its original RED and decision history.

The new56 Python and44 TypeScript cases overlap with the full-suite counts; the6 DTO cases are a subset of the44 frontend cases. Do not add them together as distinct totals. The original76 Issue8R2 tests are also inside the full frontend run. Independent validator probes reconsume the same DTOs, not new live cases.

All synthetic response fixtures are reproducible using `REPRODUCE.md`; only their hashes and bounded state-transition receipts are included. No original market payload, account/holding record, full saved workspace plan or live response body is added.

`package-tool-verification.json` records the actual check at the pre-rename local R1 path. This path was renamed to R2 after Git preflight found an existing parallel R1 branch. The command record is preserved rather than retroactively rewritten. Final R2 package/member/source verification is performed before Git sync. Git commit/ref/remote byte readback is root-owned and reported in the final delivery receipt.
