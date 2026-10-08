# Review evidence layout

The independent reviewer artifacts in this directory are byte-identical to the
reviewer's frozen 31-file allowlist. Original commands and absolute work paths
describe the environment where that independent review was actually run.

The reviewer's historical reproduction script expects the original working
layout (`baseline/`, `candidate/`, `tests/`, `test_run/`, `reviewer_final/`). Those
redundant working trees and synthetic data are deliberately not included here.
For a portable replay of the same 13 supplied cases and the reviewer's two root
identity cases in this delivery, use `../harness/run_regressions.py` as described
in the top-level README. It preserves the same exact owner source slices,
candidate bytes, test files, supplemental dependencies, before failures and
after passing expectations. The historical review scripts are provenance
records, not a deployment or Mac service entrypoint.
