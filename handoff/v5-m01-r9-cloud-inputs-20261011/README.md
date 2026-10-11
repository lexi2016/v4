# M01 R9 isolated cloud test inputs

This handoff contains the unchanged R9 engineering candidate and its independent static review. It is for isolated cloud tests only, not production acceptance or deployment. All R9 dynamic test results are **NOT_RUN** at publication.

## Inputs

- `V5_M01_A_SOURCE_R9_CANDIDATE.zip`: exact R9 candidate, patches, after-source, and tests.
- `REVIEW_M01_R9_STATIC_20261011.md`: static findings and bounded test scope.
- `MANIFEST.json`: exact file sizes, SHA-256, Git blob identities, and fixed baseline references.

Reuse the existing SOURCE and history supplement from commit `30d795bca2ed28c6b182eb8778f25dfdc2b2bc0f`, directory `handoff/v5-m01-mac-inputs-20261011/`:

- `V5_M01_SOURCE_REVIEW_20261010.zip`
- `V5_M01_HISTORY_GAP_SUPPLEMENT_20261010.zip`

These baseline ZIPs are not duplicated here. Verify their SHA-256 values against this manifest. The static report's original Library retrieval suggestion is superseded for this handoff by these fixed GitHub inputs.

## Verification boundary

Verify file hashes before extracting. Run the unchanged R9 tests first in a new isolated workspace and retain commands, interpreter/import paths, exit codes and raw logs. Known static issues include the date regular expression, overly broad FileNotFoundError scope, substring-only binding-location checks, missing root/source boundaries, and parser gaps. Record deeper cases blocked by the date issue explicitly; do not count them as passing.

Read the review before testing. Preserve active V4/V5 roots, keep canonical baseline files read-only, and do not collect market data, execute trades, wire preview production consumption, deploy, or change credential/security access. Test harness adaptation must be recorded separately from candidate changes. This publication itself runs no product code or tests.
