# M01 R10 isolated cloud retest inputs

The unchanged R10 candidate is for isolated cloud retesting only. It is not a deployable candidate or production acceptance. All R10 dynamic tests are **NOT_RUN** at publication. Root/source guards and the thin assembly adapter remain **NOT_IMPLEMENTED**.

## Files and fixed baselines

- `V5_M01_A_SOURCE_R10_CANDIDATE.zip`: exact candidate, patches, after-source, tests and checksum list.
- `MANIFEST.json`: exact byte/hash identity and baseline references.
- Reuse SOURCE/history from commit `30d795bca2ed28c6b182eb8778f25dfdc2b2bc0f`, directory `handoff/v5-m01-mac-inputs-20261011/`: `V5_M01_SOURCE_REVIEW_20261010.zip` and `V5_M01_HISTORY_GAP_SUPPLEMENT_20261010.zip`.
- R9 baseline is commit `2081745106c30f9b8da5b9179a5ea7281ce90112`, directory `handoff/v5-m01-r9-cloud-inputs-20261011/`.

The baseline packages are not duplicated here. Verify hashes before extraction.

## Retest boundary

Static inspection has confirmed three source changes: date validation, FileNotFoundError handling limited to the target read_bytes call, and exact binding relative-path equality. This is not a dynamic pass. Run the unchanged R10 tests and targeted regression/boundary cases in a new isolated workspace, recording commands, interpreter/import paths, exit codes and raw logs. Recheck remaining root/source and assembly gaps rather than treating them as fixed. Keep R9 historical results separate.

R10 uses schema `v5.m01.a_source_binding.r10`. The R9 harness valid_mapping hard-codes the R9 schema: adapt only the harness schema, first prove that a valid R10 mapping parses successfully, and then run single-field negative cases. Otherwise an early old-schema rejection can create false-green results. Do not change the product candidate for this adaptation.

Preserve active V4/V5 roots and read-only canonical baselines. Do not collect market data, execute trades, wire preview production consumption, deploy, or expand security/credential access. Any harness adaptation must be recorded separately from candidate changes. This publication changes no product code and runs no tests.
