# M07 ledger R2 isolated cloud acceptance inputs

This handoff is for independent isolated cloud tests of the M07 ledger R2 slice. It is not whole-M07 acceptance, an integration approval, or a deployment. Dynamic tests are **NOT_RUN** at publication.

## Inputs

- `M07_run_ledger_lane_patch_R2_20261011.zip`: unchanged author R2 candidate, patch, fixture and tests.
- `M07_LEDGER_R2_CLOUD_ACCEPTANCE_INPUTS_20261011.zip`: assembled fixed test dependencies, unchanged candidate, original regression tests, fixture, exact identities and test guidance. It includes the original candidate ZIP as an identity reference.
- `MANIFEST.json`: ZIP byte counts, SHA-256 and Git blob identities.

The dependency bundle uses baseline `f7cb731c384ee6890a87d16c19a5b5a621779477`. It contains eight runtime sources, including the lazy `api_gateway` dependency, and three test/fixture files. The candidate changes only the two authorized lane additions; the original ten regressions are restored. Verify package and member identities before testing.

## Test boundary and known caveats

Use a new isolated directory in the existing cloud environment. Follow the bundle's test instructions, run the original ten regression cases plus the nine new parameterized instances, and record interpreter, pytest version, commands, exit codes and raw logs. Do not infer coverage from test names. In particular, `test_all_allowed_lanes_real_claim_finish_read_reuse` only calls `identity_key`; it does not test actual claim, finish or read operations.

Write separate acceptance tests exercising real claim/finish/read/reuse for each lane, cross-lane isolation, UNKNOWN rejection, failed-run retry, and read-back success requirements. Keep those results distinct from the author's suite. Do not change candidate runtime code to make acceptance pass.

The patch has a/b headers: default `-p1` is correct for forward and reverse checks. The author's `-p0` instruction is incorrect.

Preserve active V4/V5 roots and other modules. Do not execute trades, collect market data, deploy, connect preview production consumers, or expand security/credential access. This publication adds only delivery materials and runs no product tests.
