# Handoff: 20261012 preselection date binding

**Writer status: READY_FOR_INDEPENDENT_REVIEW.** The candidate fixes the API catalog's missing source-root binding and corrects HK reuse projection for canonical V3.5 artifacts. The canonical pool schema permits the two top-level HK fields to be absent; the stage validates the exact artifact and rows itself. The API now reports `REQUIRES_STAGE_CONTRACT_VALIDATION` and leaves `stage_selection_eligible` null. Explicit false or mismatched fields still fail closed.

The candidate API canary returned `future_target_dates=[20261012]` once in the date list, A371/HK100, and `PARTIAL_WITH_ROWS`. The actual stage `_validate_hk_d1` accepted the exact HK pool at SHA `220fd29b…cfe3d`. The 10/9 17:30 dispatcher receipt is overall `FAILED` because `research_panel_runtime_evidence` failed; its `preselection_pools` workload succeeded with exit 0 for target 10/12.

Regression result: **27 passed, 1 deselected**. The deselected historical-date test fails the same way against the unchanged baseline on 2026-10-11 (`stage_dates` expected empty, got `20260622`). The new focused tests fail against baseline with 3 failures and pass against the candidate.

Changed files and SHA values are in [RESULT.json](RESULT.json); source and run evidence are in [verification.json](receipts/verification.json). The original shared `artifact.csv` path referenced by the materialized HK pool is absent from the configured shared-data root, so independent revalidation of that upstream run's manifest and receipt remains `CANNOT_CONFIRM`. No live 8873 integration, browser check, deployment, or HK selection run was performed in this writer task.

## Controller integration closure

Independent Reviewer PASS: 27 focused tests passed, exact configured Stage HK D1 input validation passed, no P0/P1/P2. Receipt: receipts/independent_review.json, SHA d1584bb62c1e29827fc09f65b3e751bd6ceb3c1aed3c9ec7531e266011abf540.

Deployed API release preselection-date-root-20261011-r1 preserves the complete previous manager-us-mapping-daily-chain release and overlays only the two frozen runtime files. No web rebuild, scheduler change, or business data write. API manifest/execution identity verified; live future_target_dates contains 20261012 and explicit selection remains 20261012. In-app browser confirms date max 2026-10-12 and URL retention, A source total 371 (200 displayed per page) and full HK100. See integration/API_VERIFIED.json, UI_VERIFIED.json, DEPLOYMENT.json and UI_20261012_POOLS.png. The default evidence date remains 20261009 by design; it no longer blocks an explicitly selected future pool date.

Prevention: shared configured source root used by pool reads and catalog, regression cases for split roots/future dates/duplicate dates/bad SHA/wrong-date trios/partial A rows/HK optional-vs-explicit metadata, independent review and actual deployed API/browser readback. Existing next-day automation also compares catalog, pool binding and selected page date. Natural selection has not run as part of this fix; original upstream artifact revalidation remains CANNOT_CONFIRM as above.
