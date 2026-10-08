# Independent review: HK Stage physical source integrity

**Verdict: `TARGETED_SOURCE_INTEGRITY_PASS_WITH_KNOWN_BASELINE_AND_DEPLOYMENT_GAPS`.** The candidate closes the demonstrated late physical-trio and root-identity validation gap for both supplied owners. No new Critical, Important, or Minor finding was identified in this bounded change. The actual `20261008 / STAGE_0930_0935 / HK_CONNECT` incident remains **BLOCKED**; this review does not approve deployment or claim that its business input has recovered.

This review was performed by an independent reviewer who authored no candidate product code. Product, supplied tests, original evidence and previous review artifacts were not modified. All executed data and writes were synthetic and confined to `reviewer_final/independent_execution/work/`.

## Exact scope and identities

The frozen problem package is commit `30ad7bb633f715f30c4e10eb67e9041de92cf036`. The only changed product file is `stage_center/_runner_parts/hk_input_validation.py`, applied independently to `canonical` and `actual_stage_owner`.

| Identity | Both owners |
| --- | --- |
| Frozen before SHA-256 | `92e8fb2be06e6530c33f3cf2f5b44f29b0bcf7875e6a5902260f8be4c814f735` |
| Candidate after SHA-256 | `b20baa18d0ee9748971db835f6fb3dd9a0e1d66aabd8da8d450aee3a4a528a8e` |
| Candidate size | 25,460 bytes |
| Supplied 13-case test SHA-256 | `2a821347da08255c001e513205ccf498377e55abbee1a2cf675ec9d24e6754b3` |

The independent runner copied each owner's 13 exact before files from `baseline/source/`, then overlaid only its candidate helper for the after run. It checked 47 input records: 26 owner before files, 17 explicitly supplemental support files, one unchanged original test module, two candidate copies and one supplied new test module. Six exercised modules were asserted by both actual loaded path and SHA at the end of every test process: runner, calendar, HK validator, PoolStore, pool readers and source resolver. Import receipts also enumerate the other loaded local modules.

The 17 support files are not a complete current runtime identity: 16 are pinned historical canonical supplements; one is a packaging alias of the current common namespace helper. The owner-specific runner, calendar, helper, Store, reader and resolver are real supplied source bytes. This is an isolated source candidate test, not a Mac application or service integration test.

## Closed finding and implementation assessment

The before helper performs a full identity comparison early in validation at lines 54–66, but its return-boundary check at lines 236–242 compares only the artifact digest and selected root pathname. A later manifest or receipt change can escape that check. Replacing the root directory at the same pathname with identical file bytes can also escape it.

The candidate retains the original Store instance at lines 136–140, preserving its captured SafeRoot identity. At lines 245–272 it reads a complete final snapshot through the original resolver or retained Store and compares payload, artifact digest, semantic digest, all three physical hashes, physical source root and all three relative paths against the earlier snapshot. Reader errors become `RunnerError`. The public `(path, digest)` return contract is unchanged. Standalone legacy input does not acquire a new physical-trio requirement.

The supplied race injection runs after the real artifact `_sha` call has read the file, so it occurs after the earlier snapshot and date/row validation. Its manifest variation leaves the HK manifest entry valid while changing the whole date manifest; the test therefore exercises exact physical snapshot identity as well as corruption rejection. The independent probe changes the source directory inode while preserving all three file bytes and the pathname. Both fail on the before source and are rejected by the candidate.

This adds a final optimistic integrity check. It does not establish a transaction spanning validation and all later consumers, nor a guarantee against every possible writer after the final read. No broader locking redesign was claimed or reviewed.

## Independent execution results

Environment: Python `3.14.7`, Clang `22.1.3`, Linux `6.18.44`, x86_64, glibc `2.39`. Interpreter: `/workspace/scratch/25c09a595aec/issue28/references/work/test-venv/bin/python`. Commands, complete console logs, JUnit and import SHA receipts are preserved in `independent_execution/RESULTS.json` and `independent_execution/logs/`.

| Owner | Suite | Frozen before | Candidate after |
| --- | --- | --- | --- |
| actual Stage | Supplied 13 cases | 9 PASS / 4 FAIL | 13 PASS |
| canonical | Supplied 13 cases | 9 PASS / 4 FAIL | 13 PASS |
| actual Stage | Reviewer root replacement, primary and secondary | 0 PASS / 2 FAIL | 2 PASS |
| canonical | Reviewer root replacement, primary and secondary | 0 PASS / 2 FAIL | 2 PASS |

Every before failure is `DID NOT RAISE RunnerError`. There were no collection errors, runtime errors or skipped cases. Counts are **15 unique parameterized cases** (13 supplied and 2 reviewer), executed on two owners and two phases: **60 executions total**, including **30 candidate PASS**. The same cases exercised on another owner or phase are not additional unique tests.

The supplied cases retain distinct failure assertions for missing split-date provenance, stale 9/30 price rows despite otherwise complete provenance, missing upstream manifest/receipt identity, and missing, naive or late eligibility capture. Valid 10/7-price and 9/30-eligibility synthetic pools still produce a fixed Top100 binding. The negative tests and positive readbacks also preserve the original pool bytes and identity where they claim immutability.

## Known baseline failures remain

The original 19-case test module was read but was **not independently rerun** in this bounded review. The root/author before-and-after receipts and `test_run/logs/BASELINE_COMPARISON.json` were inspected. They retain the same nine owner-specific failing executions: actual Stage 12 PASS / 7 FAIL; canonical 17 PASS / 2 FAIL. There are no additional failures in those supplied comparison records. This is not an all-green original suite.

Actual Stage's seven failures are:

1. `test_real_calendar_prefers_verified_exact_target_pool_as_research_observation`: returned prior-observation role differs from the expected exact-target role.
2. `test_missing_exact_target_pool_keeps_prior_connect_observation_fallback`: expected binding-mode evidence is absent.
3. `test_target_pool_committed_after_absence_probe_cannot_return_prior_fallback`: did not raise.
4. `test_corrupt_existing_exact_target_receipt_fails_closed_without_prior_fallback`: did not raise.
5. `test_pending_exact_target_pool_commit_fails_closed_without_prior_fallback`: did not raise.
6. `test_wrong_identity_on_existing_exact_target_pool_fails_closed[target_date-20261006]`: did not raise.
7. `test_wrong_identity_on_existing_exact_target_pool_fails_closed[market-A]`: did not raise.

These concern the separate Connect-closed/prior-observation behavior in the divergent owner runner. They are not repaired, waived or silently turned green by this candidate.

Canonical's two failures are `test_real_calendar_prefers_verified_exact_target_pool_as_research_observation` and `test_split_date_provenance_captured_after_eligibility_date_is_rejected`. Both stop during original fixture materialization because it omits required `d1_source_artifact_relative`. They do not demonstrate that the Stage validator accepted a late capture. The original test file remains unchanged; only the separately identified new synthetic fixture supplies that existing required field.

`KNOWN_BASELINE_FAILURES.json` records the exact cases and the hashes of inspected comparison/log/XML evidence.

## Provenance boundary and current incident

The local physical artifact SHA `62d7716c…`, manifest SHA `cc476019…` and receipt SHA `1871468d…` identify the local materialized pool. Payload `source_sha256=ce4e9422…` identifies a different upstream D1 source. Replacing the missing upstream manifest/receipt fields with the local physical hashes would mix identity layers and remains unacceptable.

The candidate makes no such substitution, changes no source payload or schema, and adds no runtime evidence fields. The existing split-date contract continues to bind `historical_provenance.d1_source_*` to the payload's upstream `source_*` fields. Passing those field comparisons is not independent verification of absent upstream producer documents.

The supplied incident summary still has no `historical_provenance` or upstream manifest/receipt pair, and all reported rows use `20260930` while the price signal date is `20261007`. Real eligibility artifact/run and the `20260930` capture evidence are not supplied as a closed chain. Adding fields or relabelling rows cannot recover these facts. This review does not assert that such original inputs do not exist elsewhere; it asserts that the present handoff does not establish them.

## Explicit NOT_RUN and declined conclusions

- Current Mac interpreter, complete runtime imports, source integration and loaded-process identity: **NOT_RUN**.
- Live Stage, ops dispatch, full slot acquisition/publication, services, launchd and natural-window execution: **NOT_RUN**.
- Actual raw price/eligibility data, upstream original producer trio and PIT/capture recovery: **NOT_RUN / NOT ESTABLISHED**.
- Deployment, restart, source replacement, business-data changes and old-slot rearm/replay: **NOT_RUN / NOT AUTHORIZED**.
- API/UI readback and current full consumer/override mapping: **NOT_RUN**; the supplied API excerpt is not the complete current consumer.
- All-green original 19-case acceptance or repair of its nine owner-specific baseline failures: **DECLINED**.
- Complete concurrency linearizability, full legacy-schema certification or every unrelated Stage path: **OUTSIDE THIS BOUNDED REVIEW**.
- Prior R1, historical P2 and prior Mac 38/38 evidence were not repeated or upgraded by this review.

The Mac acceptance document was also read for scope wording and the audit script's file-operation/state entry points were inspected. No business-root write command or recovery claim was found in that limited check. Its five tool smoke tests were not rerun and are not included in the 60 product-test executions above.

## Reproduction and packaging

From an intact package root containing `baseline/`, `candidate/`, `tests/`, `test_run/` and this `reviewer_final/` directory, use a new output directory:

```bash
"$ISSUE28_PY" -B "$ISSUE28_PACKAGE/reviewer_final/run_independent_review.py" \
  --package "$ISSUE28_PACKAGE" \
  --output "$ISSUE28_NEW_REVIEW_OUTPUT"
```

`ISSUE28_PY` must provide the recorded compatible Python/pytest environment. The runner refuses to reuse an existing output directory, checks input identities, creates isolated owner copies, preserves expected before failures, and asserts every after run is green. It writes no input source file. `DELIVERY_FILES.json` includes only this report, review source, baseline summary and compact execution evidence; it excludes isolated owner copies, caches and synthetic fixture directories.
