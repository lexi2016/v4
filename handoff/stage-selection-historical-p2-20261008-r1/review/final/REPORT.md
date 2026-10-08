# Independent final source review — historical P2 continuation

**Verdict: PASS_WITH_DEPLOYMENT_GAPS for the two supported source changes.** No Critical, Important or Minor defect was found in this bounded changed-code review. The third historical P2, rejection of unknown nested provenance fields, remains **DEFERRED and unresolved**. This verdict does not approve deployment or claim that Issue #28, historical data, Mac integration or PIT verification is complete.

The review covers only the date upper bound in `infrastructure/preselection_pool_store.py` and the existing uncertainty reason in `ops/build_close_review.py`. It follows the unchanged preimplementation compatibility matrix and `evidence/README.md` section 7. No product or supplied test source was edited by this reviewer.

## Exact reviewed images

The before-images match the original frozen canonical source at commit `00524e9050fe212f87911b56eea1c2db719dd94b`. These are source candidates, not identities for a current Mac process.

| Product | Before SHA-256 | After SHA-256 | Candidate location |
|---|---|---|---|
| Pool validator | `028298a05ea44e310487c1159acc8147cf652e23ba716989135b178198795a92` | `9f1606a977d36c063d9c650e54b9861947eb7b692e779837852e3831b7814bef` | `../../historical_validation/after/infrastructure/preselection_pool_store.py:363–365` |
| Close producer | `a361ae023285392ddf3b0e9674a9c506fae79252cc02c15df221ae09ba28e5aa` | `59ac7798bcb1d54bbd11bbc61803997f36881a29cd1b82ecb663166791d5e0f2` | `../../close_pit/after/canonical/ops/build_close_review.py:146–156` |

The pool file changes from 56,442 to 56,638 bytes; the close producer changes from 6,601 to 6,843 bytes. Independent checks verified the close batch's 20 pinned source/support records and the date batch's 27 records, then rechecked them after execution. Counts refer to each batch's records and include shared dependencies. See [CLOSE_IDENTITY_CHECK.json](CLOSE_IDENTITY_CHECK.json), [DATE_IDENTITY_CHECK.json](DATE_IDENTITY_CHECK.json) and [FINAL_VERIFICATION.json](FINAL_VERIFICATION.json).

## Findings and reasoning

### 1. Source dates are bounded without changing historical capture semantics

The three added lines at pool-store lines 363–365 compare both canonical provenance dates with normalized `trade_date`. The outer validator already requires optional `target_date` to equal `trade_date`, so omitting that optional field cannot bypass the new rule. Existing date-format and source binding checks remain in place.

The focused suite demonstrates rejection of future eligibility and price dates in both supported historical schemas, including an omitted `target_date`. It also preserves equality with the target in both schemas, valid split dates, the original contract test, generic provenance-free shapes, known optional metadata and open input-digest labels. The original late recovery fixture still materializes and reads back with its exact October 2 capture timestamp for the September 30 target and false safety/natural flags. These are historical storage semantics; the separate Stage/PIT gate is unchanged and was not executed. Evidence: [date JUnit](historical_validation/after.xml).

**User-visible consequence:** an already stored pool with a future provenance source date will now fail validation when read. It is not repaired or overwritten. Two independent probes verified that transition through the real store:

| Independent probe | Exact before store | Exact after store | Preserved evidence |
|---|---|---|---|
| As-of schema: eligibility `20261001`, target `20260930` | Materialized and read the internally bound fixture | Rejected read with `historical pool source date exceeds target date` | Artifact, receipt and manifest bytes identical |
| Split schema: price `20261008`, target `20261007` | Materialized and read the internally bound fixture | Same expected rejection | Artifact, receipt and manifest bytes identical |

The reviewer loaded and executed the exact before-store bytes separately, then used the final after-store reader. Each probe records all three before/after SHA-256 values. See [as-of read probe](combined/read_probe_asof_eligibility_source_date.json) and [split read probe](combined/read_probe_split_price_signal_date.json). No actual business store was inspected for these conditions.

### 2. Missing upstream evidence adds the existing uncertainty reason

The close producer extends its existing branch to cases missing either `source_manifest_sha256` or `source_receipt_sha256`. It appends `HK_MODEL_SOURCE_PIT_AVAILABILITY_CANNOT_CONFIRM` once through the existing `cannot_confirm` list. Provided SHA values have already been checked by the real pool store. No new output schema, date-specific branch, source identity or timestamp is introduced.

Tests cover each missing field separately and both missing, on two fixture dates. Native review publication and readback preserve the marker. The complete nonhistorical source pair produces the same review as the frozen producer, and the missing-pair comparison differs only by the added reason. Model rows, metrics, status calculation and false safety flags remain unchanged. A complete SHA pair is not a new PIT certification.

The original exact absent-pool sentinel still produces a model-source gap, now with the additional uncertainty reason. Missing local manifest/receipt and corrupt receipt data continue to raise before review publication. The new code does not catch those failures. Source pool evidence remains unchanged during generation; previously saved review/receipt bytes remain unchanged during readback. The existing explicit rebuild/CAS publication behavior remains intact. Evidence: [standalone close JUnit](close_pit/after.xml).

### 3. The two final source files work together in the supplied scope

The standalone close harness intentionally uses the original PoolStore. A separate independent worker therefore ran the same 14 close cases with the new date validator loaded. It checked each module's actual `__file__`, SHA-256 and the identity of `build_close_review.PreselectionPoolStore`, before and after execution. All 14 cases passed, along with the two independent existing-artifact read probes.

The worker changes only its own in-memory import path; it does not edit either author's harness, source or identity manifest. In this combined run, supplied comparisons using `before_producer()` compare frozen close code with the candidate PoolStore. The two independent read probes explicitly load the exact original PoolStore separately. This distinction is recorded in [COMBINED_RUN.json](combined/COMBINED_RUN.json).

## Executed tests and counts

Environment: **Python 3.14.7**, pytest **9.1.1**, Linux **6.18.44 x86_64**, glibc **2.39**. Interpreter: `/workspace/scratch/25c09a595aec/issue28/references/work/test-venv/bin/python`. These tests use synthetic local inputs, real source validators, real disk stores and readback.

| Independent execution | Supplied cases | Reviewer-authored cases | Result |
|---|---:|---:|---|
| Close candidate with original PoolStore | 14 | 0 | 14 PASS |
| Date candidate | 13 | 0 | 13 PASS |
| Both candidates plus existing-read probes | 14 repeated | 2 | 16 PASS |

There are **27 unique supplied cases**, **14 additional executions of those cases for composition**, and **2 unique reviewer-authored probes**. That is **43 passing executions across 29 unique cases**, with no failures, errors or skips in these fresh runs. No R1 suite, broad application suite or optional extra test round was run. Detailed names and counts are in [TEST_RESULTS.json](TEST_RESULTS.json).

The unchanged original historical contract test and fixture functions are selected from a SHA-checked frozen file through AST extraction. No pool validator, I/O component or review store is mocked. Close fixtures pass `stage_selection_root=None`; the harness has an explicit unused Stage-consumer import sentinel that raises if constructed. Stage integration is therefore outside the tested scope.

Actual commands and environment are preserved in `close_pit/after.json`, `historical_validation/RESULTS.json` and `combined/COMBINED_RUN.json`. Portable replay uses the bundled directories and explicit arguments:

```bash
python -B /path/to/close_pit/run_tests.py --phase after --output /path/to/new-close-results
python -B /path/to/historical_validation/run_validation.py --mode after --log-dir /path/to/new-date-results
python -B /path/to/review/final/run_combined_review.py   --close-root /path/to/close_pit   --historical-root /path/to/historical_validation   --output /path/to/new-combined-results
```

Use new output directories to retain prior evidence. The combined runner requires the adjacent `test_existing_future_artifact_read.py`. It reuses the authors' bundled support and performs explicit candidate path/hash checks.

## Retained failures and unresolved nested P2

The following are **author executions**, independently inspected and parsed here, not rerun or relabeled as fresh reviewer tests:

| Retained evidence | Result | Meaning |
|---|---|---|
| Original close producer, focused suite | 8 FAIL / 6 PASS | Missing-marker regression evidence |
| Original date validator, focused suite | 5 FAIL / 8 PASS | Future-date rejection assertions failed with `DID NOT RAISE` |
| Nested unknown-field probes, before | 2 FAIL | Known unresolved P2 |
| Nested unknown-field probes, after | 2 FAIL | Same unresolved P2 remains |

The nested failures are **not passing tests**, even though the author's orchestration can successfully recognize the expected RED result. The after validator at `../../historical_validation/after/infrastructure/preselection_pool_store.py:367–400` still accepts an unregistered key in either nested schema object. No nested allowlist is claimed or approved.

The inspected original consumers and minimal fixture establish some required and optional fields, but not the complete original emitters/schema. The retrieved recovery test points to an external Mac recovery package, bound source archive and actual recovery objects. Those contents are absent. A fixture-derived allowlist could reject legitimate sealed recovery evidence, while freezing input-digest labels would incorrectly constrain an open map. This P2 remains **DEFERRED_PENDING_ORIGINAL_PRODUCER_SCHEMA_AND_OUTPUTS**. See [SUPPLIED_FAILURE_EVIDENCE_SUMMARY.json](SUPPLIED_FAILURE_EVIDENCE_SUMMARY.json).

## Explicit limits and declined judgments

| Area | Status and reason |
|---|---|
| Actual August 25, September 30 and October 7 historical data | **NOT_RUN / NOT_SUPPLIED.** No actual historical raw pool, review, receipt or complete source closure was restored. The missing-evidence fixture is not an independent reproduction of August 25. |
| Current Mac owner and complete dependency closure | **NOT_RUN / CANNOT_CONFIRM.** Frozen canonical source and historical support do not identify the currently loaded application. |
| Stage, API and UI | **NOT_RUN.** No actual Stage consumer, canary, HTTP API, UI or full application suite was executed. |
| Natural execution and comprehensive PIT | **NOT_RUN / CANNOT_CONFIRM.** No original-slot capture or natural execution evidence was reconstructed. Late recovery remains unverified; a complete SHA pair is not proof of historical availability. |
| Deployment, services and business writes | **NOT_RUN / NOT_AUTHORIZED.** This is source review only; no Mac install, service control or business-data mutation occurred. |
| Nested unknown-key P2 | **DEFERRED and unresolved.** Two rejection probes fail before and after. Exact original schema/producer/output evidence is required before a compatible fix can be reviewed. |
| R1 and unrelated Issue #28 work | **NOT_RERUN.** The earlier auction, release, HK and pool review is preserved; this report does not extend its runtime or deployment claims. |

The preimplementation matrix, prior R1 review/closure reports and original failure logs/XML were verified unchanged: 16 preserved files are recorded in [FINAL_VERIFICATION.json](FINAL_VERIFICATION.json). The delivery allowlist includes only reviewer source, reports, identity/preservation records, logs/XML and probe summaries. It excludes temporary stores, caches and generated fixture artifacts.
