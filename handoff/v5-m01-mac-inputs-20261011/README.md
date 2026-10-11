# M01 R6 Mac isolated acceptance inputs

These immutable inputs are an isolated engineering candidate and source-review handoff. They are not production acceptance or a deployment. Mac tests are **NOT_RUN** at publication.

## Contents

- `V5_M01_A_SOURCE_R6_CANDIDATE.zip`: candidate runtime patch, reverse patch, after-source, tests, and checksums.
- `V5_M01_SOURCE_REVIEW_20261010.zip`: fixed source-review baseline and dependencies.
- `V5_M01_HISTORY_GAP_SUPPLEMENT_20261010.zip`: fixed history-gap source supplement.
- `REVIEW_M01_R6.md`: independent static review and bounded Mac test scope.
- `MANIFEST.json`: exact byte counts, SHA-256 and Git blob identities.

## Use and limits

1. Retrieve this directory from the fixed publication commit, then verify all four files against `MANIFEST.json` before extracting.
2. Read `REVIEW_M01_R6.md` first. Known defects include incomplete identity reuse, broad exception handling, root-boundary/assembly gaps, and strict parsing gaps.
3. Work only in a new isolated checkout/fixture directory. Preserve active V4 and V5 data roots. Do not collect market data, execute trades, enable preview production consumption, or change security/credential access.
4. Use the fixed original SafeRoot and source reader for the review's bounded engineering tests. Record passed, failed and NOT_RUN cases separately.
5. The candidate's `reverse.patch` has the same bytes as `runtime.patch`; reverse application requires `git apply -R runtime.patch` (check with `git apply --check -R runtime.patch` first).

This publication only adds these delivery materials. It does not apply the candidate patch, change runtime code, run tests, merge branches, or deploy the system.
