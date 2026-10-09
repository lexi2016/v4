# Independent frontend deployment-readiness review

**Overall result: DEPLOYMENT_READY=FAIL** for manifest `042044b644a370d75d8224655a38374b9b5c91af7a0863681b02509b88787c6c`, staged plist `5f404da97b115d5cd217bcd10f9dc0430a9bac2ccf9d57482a1f85df568ea0d1`, and corrected plan `276804d7e7ed1c7933d9e9838995a6ae44ba63a3b97b7efe039e81523b9c5a87`. Do not cut over until the P1 below is resolved and independently rechecked.

## P1: 45 existing observation-contract regressions in the integrated release

The candidate frontend removed the validator functions/calls for `research_attention.observation_only`, `research_attention.input_diagnostics`, and their cross-field/display consistency checks. The frozen rollback baseline contains `validateIndependentObservations`, `validateResearchInputDiagnostics`, and `validateResearchDisplayConsistency`, called from `validateResearchAttention`; the candidate has none of those names/calls. Candidate `validateManagerWorkspace` still invokes `validateResearchAttention` for workspace payloads, but that validation now returns without checking those fields.

Independent comparison used the same 8 existing Vitest specs, identical test-source SHA values, the same Node/Vitest dependencies, and the same Python 3.14.6 environment. On the exact rollback baseline, `issue8R2.spec.ts` passed all 76 tests. On the integrated candidate, 45 of those same 76 tests failed because malformed observation containers, counts/statuses, promotion/safety claims, external references/URLs, time/PIT fields, and cross-field identities no longer throw. Candidate total was 59 failed/170 passed vs baseline 14 failed/215 passed across the same 229 tests; all 14 baseline failure IDs remained the same and the 45 additional failures are confined to `issue8R2.spec.ts`.

Evidence:

- Candidate: `app/apps/web/src/api/managerWorkspace.ts`, `validateResearchAttention` begins at line 1197; the function validates the attention identity/cards and optional selection ledger but omits the two nested validators. `validateManagerWorkspace` still calls it at line 1514.
- Baseline: `rollback/issue32_predeploy_20261009/app/apps/web/src/api/managerWorkspace.ts` contains the three validators at lines 899, 930, 955, and invokes nested observation/input checks at lines 1114–1115 and display consistency at line 1380.
- Actual module SHA: rollback baseline `6bd208174c650beb1b089058de458643beb601a97455ff472330984e88dd6d7d`; candidate `35a879624032cfffb1c3e4afba3c4ae6298df7d5dffb5db90d9ad42142f496ee`.
- The unchanged test file SHA is `3b8e004f31135674d63c1affd25cc41d759bfd10187a1dfc318f64c53636f873`. Example failing assertion: `issue8R2.spec.ts` case “rejects unsafe URL” expects `validateManagerWorkspace` to throw; candidate log records “expected [Function] to throw an error,” while the same case passes on baseline.
- Full comparison receipt and per-run logs: `review/tmp/legacy-frontend-baseline-r1/legacy-frontend-failure-classification.json`, `logs/rollback_base.log`, and `logs/integrated_candidate.log`.
- Reproduce with `/Users/lexi/Desktop/学习/v4_app/.venv/bin/python -B review/compare_legacy_frontend_failures.py`. The receipt enumerates all 45 new candidate-only failed test IDs; baseline/candidate test sources have equal SHA values.

This is a behavioral validation regression, not a test-fixture/environment failure. Whether a separate backend validator prevents malformed data from reaching this UI is `CANNOT_CONFIRM`; it does not make the candidate frontend contract pass.

## Other frontend evidence

- Exact final-release changed-source typecheck: PASS.
- Independent targeted UI regressions: 25/25 PASS after copying the frozen test-only Python fixtures into a review-owned full-app copy and selecting the existing venv.
- Independent Vite build: PASS; the review-copy build’s 16 `dist` file hashes exactly match the final release. Candidate source tree and canonical Vite cache were unchanged.
- Earlier full-matrix output had 72 failures. Classification against the frozen base: 14 failure IDs pre-exist unchanged; 13 failures in the two targeted DTO suites came from the earlier runner’s missing fixture/Python environment and passed in the corrected 25-test run; the remaining 45 are the candidate-only `issue8R2` validation failures above.
- Plan-review gate: PASS, separately receipted at `review/execution_plan_review_20261009.md`.
- Live deployment, API/UI runtime readback, and natural-date behavior were not run and are not prerequisites for this pre-deployment verdict. No service, LaunchAgent, API, or business state was changed.
