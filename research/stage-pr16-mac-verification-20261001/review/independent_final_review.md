# PR16 independent review — frozen PASS scope

**Verdict:** `REVIEWED_WITH_P2`; the isolated candidate and the requested 10 synthetic regression cases pass. The full frozen PASS is not confirmed until the candidate current/run identity boundary is resolved. No P0 or P1 finding.

## Evidence reviewed

- Writer handoff: `writer/WRITER_RECEIPT.json` SHA-256 `84ce1445c8725990edc05c85220f97291f22a3455e04133709595ad40ecd96cb`. It correctly leaves `TESTED=false`; this independent rerun is recorded separately.
- Actual seven-file diff: `writer/actualdiff.patch` SHA-256 `e6a0d2e39941786f2291b57fe1a8d721de4983f69312e19288f841c522ac32bb7`. It covers the four Stage runtime files, two test files, and the ordered-code fixture.
- Candidate identity: fixed commit `84264c47a99d464d174b8180375c8701883b2bb5`, source SHA `22d24b3f473649f8253215265767a9c1e520f7a1a9838e1d967fe7389bcf7623`; candidate manifest SHA `9cef626583df3e9c0bddde1d2d517cbe2d96830db425241237cc6e131ccc56fe`.
- Independent integrity check: all 692 manifest files matched byte count and SHA, with no extra files or symlinks; all 50 Stage-closure pins matched (48 direct pins, 2 PR16 after-pins), and all 5 external dependency pins matched. Receipt: `review/pr16_candidate_integrity_review_receipt.json` SHA-256 `8014a5e03cebc2c529bc87641690f30b484122a52d4799238777f9a89cc57967`.
- Independent rerun: exactly 8 digest tests and the 2 A-only success/exception instances, on the recorded Stage interpreter Python 3.14.6 / pytest 9.1.1. Both invocations exited 0; JUnit reports 8/8 and 2/2 passed, with zero failures/errors/skips and empty stderr. Candidate hashes were unchanged. Receipt and logs: `review/pr16_reviewer_tests_20261001/receipt.json` SHA-256 `8859071ba3964b6fec7a00636311e326b4ad61ebac24e00f0a4334168a848311`.

## P2 finding

**A0925 authorization does not bind the frozen current/run identity.** The frozen scheme asks to verify the candidate current, artifact, and run identity (`coordinator/scheme.md:16`). The guard’s required authorization fields pin the original receipt, artifact SHA, and codes SHA (`writer/candidate/ops/_run_stage_center_nodes_parts/node_entry.py:659-663`); its candidate check compares artifact SHA and ordered codes only (`:718-722`). It returns `candidate_current_sha256` and `candidate_run_id` after acceptance (`:745-754`) without comparing them to the authorized/original values. The new digest-test fixture supplies `current_sha256="1" * 64` and `run_id="SYNTHETIC_GUARD_ONLY"` while retaining the pinned artifact SHA (`tests/test_pr16_issue11_codes_digest.py:82-95`).

The staged A0925 verification identifies the actual reported tuple as current SHA `08b1a6b0376c1ba0828ed5b3423ef5860d4e66944342cf3cf74d28b189e21623`, artifact SHA `92023837d8709abfb46fb03dec82ee9758ff56e57615cdfebeb98926e3789d72`, run `20260930-a_share_stage_acquisition_universe_v3-92023837d870`. The review did not read active data/attempt paths, so whether a different valid current/run can exist with the same artifact is `CANNOT_CONFIRM`; the code itself does not enforce the exact tuple. If the frozen acceptance requires exact lineage, add explicit current/run pins to the authorization and test rejection when either changes, or record a scope decision that artifact-plus-ordered-codes is the intended boundary.

## Evidence limits

- The writer’s A0925 evidence metadata reports all six original START/RETURN hashes and sizes matched. The original receipt, six attempt files, current pointer, and artifact were outside this review’s allowed read scope, so those raw identities were not independently recomputed: `CANNOT_CONFIRM`.
- The 10 rerun tests validate the digest guard and synthetic A-only success/exception behavior, including HK preservation and one-shot consumption. They do not establish a real Stage run or formal loaded-module byte identity; the writer receipt also marks those unknown.
- The corrected A1445 recheck binds the frozen source/archive pair (`review/a1445_original_archive_recheck.json`, binding `PASS`). The corrected script/witness/receipt hashes agree and its captured rebuild exited 0 with empty stderr; producer execution bytes, original serializer identity, and real Stage/API behavior remain `CANNOT_CONFIRM`. The earlier A1445 pin-transcription P1 is withdrawn; the frozen `811b...af0` archive pin is correct.
- The HK supplement documents separate D-1/cutoff failures and leaves owner capture linkage `CANNOT_CONFIRM`; the PR16 diff contains no HK source changes.

The Stage exception instance asserts the A-only call, preserved HK selection, attempt count, and consumed marker. It does not assert the first exception response’s A-lane status/error representation; the captured synthetic receipt contains `PARTIAL_COMMIT_RETRY_REQUIRED` with `SYNTHETIC_A_BUILDER`, while A’s nested `status` is `READY`. That field’s intended meaning for a failed selection is `CANNOT_CONFIRM` from this review because the focused test and downstream status contract do not settle it.

**Status:** `TESTED` — independent 10-case rerun PASS. `REVIEWED` — with the P2 above. Synthetic behavior is verified only within the bounded test fixtures; formal/natural behavior remains `CANNOT_CONFIRM`.
