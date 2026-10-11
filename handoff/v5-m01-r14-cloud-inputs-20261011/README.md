# M01 R14 isolated cloud parser/core inputs

The unchanged R14 candidate is for parallel isolated cloud tests of restored parser/core behavior, while known missing pieces are reported separately. It is not a deployable candidate or production acceptance. All R14 dynamic tests are **NOT_RUN** at publication.

## Inputs and fixed baselines

- `V5_M01_A_SOURCE_R14_CANDIDATE.zip`: exact candidate, patches, after-source, tests and checksum list.
- `MANIFEST.json`: byte/hash identity and fixed baseline references.
- Reuse SOURCE/history from commit `30d795bca2ed28c6b182eb8778f25dfdc2b2bc0f`, directory `handoff/v5-m01-mac-inputs-20261011/`: `V5_M01_SOURCE_REVIEW_20261010.zip` and `V5_M01_HISTORY_GAP_SUPPLEMENT_20261010.zip`.
- R10 baseline is commit `62deec72c684e4cea25d7cedd526e09ead2304ba`, directory `handoff/v5-m01-r10-cloud-inputs-20261011/`.

Verify hashes before extracting. The source/history packages are not duplicated here.

Known packaging defect: SHA256.txt includes an incorrect self-referential entry. Its actual SHA-256 is 930d1303065e43d034dd7172d974c6b28288b4749dc4c8b096a257c9aeb6797d. The other five member entries and the external ZIP SHA are verified. Preserve this unchanged candidate, record the checksum-list defect explicitly, and use the verified external ZIP/member identities for testing; do not silently rewrite the package.

## Harness adaptation and evidence

R14 uses schema `v5.m01.a_source_binding.r14`. Adapt only the independent harness's schema and recorded API bindings. First prove a valid R14 mapping parses successfully; then run single-field negative cases, preventing stale-schema rejection from creating false-green tests. Do not modify the product candidate or author tests.

In the existing R10 harness, update both valid_mapping and the test_valid_r10_mapping_baseline schema assertion to R14. The old diagnostic test test_invalid_calendar_date_is_rejected_valueerror expected ValueError; R14 now correctly wraps it as M01BindingError, so update that independent-harness expectation and record the change. The first create_binding parameter is now safe_root; positional calls with reader= remain compatible, but private_root= is not the current keyword. Existing root cases that call only the low-level core do not prove the new roots wrappers; add separate wrapper cases with explicit real dependencies and keep the missing default path separately reported.

The restored core APIs are `create_binding(safe_root, generation_pointer, target_date, reader)`, `read_and_verify_binding(safe_root, relative, reader)`, and `verify_binding_bytes(raw, relative, reader, expected=None)`. Exercise them using fixed original SafeRoot/reader dependencies where applicable, recording all injection/fixture choices. Run original tests separately from independent acceptance.

## Known missing pieces

The root-facing create/read wrappers still require four caller-supplied dependencies: SafeRoot, reader, no_symlinks and shadow_root. Default dependency entrypoints are **NOT_IMPLEMENTED**. Supplying them in a test does not prove a default entrypoint works.

The context helper checks root overlap and marker, but the returned source root is not used to restrict the original pointer, stored generation_path or reader-returned path. A bounded source reader/source-containment guard is **NOT_IMPLEMENTED**. Test/report that gap separately; successful parser/core tests do not close it.

Use new isolated fixture/output roots. Record commands, interpreter/import paths, exit codes, raw logs and unchanged-runtime hashes. Preserve active V4/V5 data and read-only canonical baseline files. Do not collect market data, execute trades, deploy, wire preview production consumption, or expand security/credential access. This publication changes no product code and runs no tests.
