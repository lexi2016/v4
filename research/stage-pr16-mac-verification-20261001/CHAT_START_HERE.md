# PR16 macOS evidence handoff

This package records a fixed-commit, local candidate and bounded verification. The candidate tree is an edit-and-test artifact; it is not a deployable release, a loaded service image, or proof of a real Stage recovery.

## Fixed source identity

- Repository: lexi2016/v4
- PR16 source commit: 84264c47a99d464d174b8180375c8701883b2bb5
- PR15 source-inventory commit: bdc95a3f9d6d0313baeff2bf727ea82d122dc820
- The compact source manifest retains all 692 candidate path/SHA/origin rows, the 50-row Stage closure, the overlay-contract pin, and five external Stage dependency files. It does not contain the 692-file source tree.
- The exact actual diff and source-only rollback patch are preserved byte-for-byte. The diff includes its pre-existing A0925 test fixture; this package does not export another copy of the 205-code array.

## Verification and review

- Writer auxiliary run: 8 PR16 digest tests plus 2 A-only R4 success/exception cases passed on the configured SERVICE_PYTHON (Python 3.14.6, pytest 9.1.1).
- Independent reviewer replay: the same 10 targeted cases passed. The independent final verdict is REVIEWED_WITH_P2, with no P0 or P1.
- P2: A0925 guard pins the artifact SHA and ordered codes but does not additionally compare current.json SHA or run_id with the frozen tuple. Whether current/run changed in the actual natural run remains CANNOT_CONFIRM. The frozen task scope accepts this as a recorded gap; this package does not add a new gate or claim natural recovery.
- Review did not directly re-read the original A0925 receipt, attempt files, current file or artifact. Their identities are presented as the writer's hash-checked evidence, preserving the independent review boundary.

## Evidence results

- A0925 formal receipt is CANNOT_CONFIRM after three exhausted recovery attempts with six preserved event hashes. A current artifact/run identity with 205 unique ordered codes is hash-bound in the staged evidence. No natural full-input recovery or formal loaded-module identity is established.
- A1445 uses the verified original pair: source raw SHA 4076de79920c43cfa57336c23262a491cd77730f29b4e1a530bc5ed9836ef571 and archive stored-payload SHA 811b7803b540ec22c8e3f061804229e59fa51179f20a55a56ccc12d946af4af0. The read-only reconstruction reports 27 JSON Pointer differences at /cannot_confirm/1 through /cannot_confirm/27. The original producer bytes, actual historical loaded modules, and real Stage/API behavior remain CANNOT_CONFIRM.
- The A1445 correction note records that an earlier e8c3 transcription was withdrawn after direct owner-root verification. The package-only repro script is transformed and accepts --app-root and --data-root; its exported SHA is not the original evidence-script SHA.
- HK evidence keeps strict D-1 inputs separate. The minimum missing lineage remains: 9/28 active snapshot original bytes/time/owner link; 9/29 cutoff-before active snapshot and owner receipt; and 9/29 security-master same-capture artifact/owner manifest linking the 9/30 invalid sentinel. The failed 9/29 dispatcher retries are not capture artifacts. The 9/30 canary and 15:02 snapshot are not substituted for morning evidence.

## Safety and status

production_allowed=false; buy_gate_updated=false; orders_sent=false. No service, collector, producer, real runner, or source data was changed by the candidate or evidence packaging. No GitHub push was performed.

IMPLEMENTED: candidate work is represented by pinned diff and source manifest. TESTED: independent 10-case replay passed. REVIEWED: REVIEWED_WITH_P2. INTEGRATED, DEPLOYED, API_VERIFIED, UI_VERIFIED and NATURAL_VERIFIED remain CANNOT_CONFIRM.
