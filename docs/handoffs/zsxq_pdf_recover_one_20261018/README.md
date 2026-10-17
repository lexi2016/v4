# Single-document PDF recovery candidate

Offline implementation and independent acceptance complete. This candidate has not been deployed and no real recovery was performed.

| State | Result |
|---|---|
| IMPLEMENTED | YES, three scoped source/test paths |
| TESTED | Focused offline tests independently rerun |
| REVIEWED | R2 PASS; initial R1 P1 was repaired |
| BEHAVIOR_VERIFIED | PASS_OFFLINE within frozen scope |
| RECOVERED | NOT_RUN |
| DEPLOYED | NOT_RUN |

Baseline remote commit: `d56d0ea45374764b2f28ab14ead8426752a0f8d1`. Candidate branch: `codex/zsxq-pdf-recover-one-20261018-r1`. Source root: `/Users/lexi/Desktop/学习/v4_app`. This branch preserves the prior PDF handoff baseline; it is not a complete snapshot of all current deployed application changes and must not be deployed wholesale.

The entry binds document key, date, source run and source signatures; it claims one recovery event durably under the existing lock. Guard, consumed-index entry and audit copies must agree. Repeat, concurrent, altered-authorization and ambiguous interrupted calls cannot silently obtain another recovery opportunity. Clean verified checkpoints support at most two pages per continuation under the same authorization. Existing metadata/URL/PDF/cache validation and processing are reused; global MAX_ATTEMPTS remains 2 and the URL parser is unchanged.

The first independent review reproduced a direct module-call bypass around claim validation. The repaired path now validates the persistent exact claim before writes/callbacks. The original isolated repro is rejected with PDF_RECOVERY_CLAIM_INCOMPLETE. R1 FAIL evidence and R2 PASS evidence are both retained.

Verification: Writer final PDF-ingestion suite 42 passed; independent R1 suite 40 passed on the initial candidate, then independent R2 reran the three directly affected regressions (3 passed, 39 deselected) plus the original bypass repro on final SHAs. The R2 subset covers unclaimed direct invocation, consumed-checkpoint matching, and valid two-page recovery continuation. The full 42-test final suite was NOT independently rerun. Runtime: Python 3.14.6, macOS 26.6.2 arm64, uv --offline. One existing Starlette/httpx deprecation warning. Exact commands/results are in the receipts.

Final read-only integration check: live data-index SHA `3f279b93b48c13ed32651292b7a72339f8a19712bae731de3277f924e1141239`; equals frozen before-SHA: `true`. The scheduler and API releases still contain the old accepted module SHA `727a3f6cfcef626d6cf482eebf9e8d66418fcbe9817ae2e1dd1943c88e8384e0`; the candidate module SHA is `5dedf912a9cc8b41646a5cfb0133ded4dbaa0168aae74157e75e4498cd1fd915`. No live authorization was generated, no PDF downloaded, no OCR or queue triggered, and no service/release changed. The prior 321 failed records remain outside this execution batch.

Frozen possible future canary: document_key `0273668ed1af2435f2a73167ac5282e1dfecd92b9b63e4dbfe873a07719ff684`, date `20261017`, source_run `20261017_130000_130000125862`. Inactive invocation is in writer-receipt.md. A real canary requires a separate explicit execution decision and fresh identity/source checks; this candidate receipt does not authorize live data writes or mass recovery.

Rollback boundary: revert only the three scoped candidate source/test files to their frozen baseline bytes through the normal reviewed change path, preserving concurrent edits. No runtime rollback or shared-data edit is part of this batch.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.
