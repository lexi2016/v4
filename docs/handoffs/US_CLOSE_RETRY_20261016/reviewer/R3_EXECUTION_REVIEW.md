# US close retry R3 execution review

**Verdict:** `REVIEWED: PASS` · `BEHAVIOR_VERIFIED: true` for the frozen candidate's isolated synthetic behavior.  
**Scope:** Candidate release manifest `3793d0acb6937828fccc0c6f1a5331be699e7ad62ac448654050a62ab70225a`; business date `20261016`, US session `20261015`; R3 runtime delta, US-owner-only CAS activation helper, and manual recovery receipt path. R2's review receipt remains intact.

This was a read-only review. No producer capture, research-data write, service activation or rollback, API/UI readback, or natural-session behavior was performed.

## Findings

- **P0:** None found.
- **P1:** None remaining in the frozen R3 scope.
- **P2:** The manifest-check ordering race is fixed. `candidate/us_only_cas_activation.py:232` completes the manifest hash check before the final active-US-plist hash at `:244`, adjacent to `os.replace` at `:247`. The test `test_manifest_check_race_rechecks_plist_before_replace` starts at `candidate/evidence/test_cas_activation_race.py:113`; its assertion at `:132` confirms the concurrent bytes remain intact, while `:133` confirms the temporary file is removed. Ordinary POSIX compare-then-rename still cannot prevent a separate process from writing after the final hash read and before `os.replace`; this remaining interval is `CANNOT_CONFIRM` for any future external writer. It is recorded as a platform limit, not a blocker for this bounded batch.

The earlier quote-scope defect is corrected: the configured US owner loads and validates the existing universe contract in the candidate app's `ops/us_market_digest.py:135` and returns the validated contract at `:156`; `ops/_us_market_digest_parts/market_snapshot.py:74` begins contract validation, and `:95` builds the request from those contract symbols. The output records the contract and requested/available counts at `:266` and `:267`. The candidate-rooted synthetic test asserts a V3 contract with 48 requested, available, and quoted symbols at `candidate/evidence/test_us_close_retry_candidate_rooted.py:645` and `:657`. Unconfigured legacy callers remain on the V2 33-symbol contract, covered by `candidate/evidence/test_candidate_legacy_33.py:12` and `:33`.

The recovery script pins the six proxy variables at `candidate/recover_20261016_post_close.sh:36` and invokes the collector without an explicit run ID at `:42`. The collector now generates a UTC `Z` run ID that conforms to its safe-ID regex at `candidate/evidence/collect_us_recovery_receipt.py:85`; the no-ID regression test starts at `candidate/evidence/test_recovery_collector.py:91` and verifies both receipts at `:125` and `:129` under `TZ=Asia/Shanghai`.

The retry path was independently exercised for both daylight-saving variants. The parametrized test starts at `candidate/evidence/test_us_close_retry_candidate_rooted.py:677`; it checks receipt-chain validity at `:823` and idempotent repeat behavior at `:834` after asserting retry slot/session/trade-date binding and 48-symbol V3 snapshot publication.

## Acceptance evidence and limits

- Candidate-rooted business/legacy suite, run with the candidate app root as the import root: **11 passed**. The separate legacy/CAS/collector evidence suite: **10 passed**, including the new default-run-ID and manifest-window race probes.
- Candidate manifest read-back SHA remains `3793d0acb6937828fccc0c6f1a5331be699e7ad62ac448654050a62ab70225a9`. The handoff checksum ledger entries for the CAS helper, collector, and both focused test files match the current file hashes.
- `tests/test_us_recent_rss_recovery.py` passes **4/4** against current canonical source and **3/4** against the candidate app. The candidate-only failure is in its unchanged `infrastructure/research_peripheral_store.py`: the legacy manual RSS-only recovery fixture emits `MANUAL_RSS_ONLY_RECOVERY_LATEST_COMPLETED_SESSION`, while that frozen baseline validator accepts only `NATURAL_SLOT_MISSED_CONTROLLED_RECOVERY`. The store is unchanged in the R3 inventory delta and this RSS-only path is outside the frozen close-retry target, so this does not block R3. Whether the candidate supports that separate legacy manual-recovery path remains `CANNOT_CONFIRM`.
- The candidate receipt reports the source close-retry suite at 32 passing tests and the unchanged packaged test preimage comparison at 6 failed / 5 passed for both old release and candidate. I did not rerun either suite; the independent candidate-rooted and focused evidence results above are the R3 reviewer reruns. Whether the packaged-suite failures affect this modular candidate remains `CANNOT_CONFIRM` because the same node IDs fail on its frozen preimage.
- No real `20261015` capture, provider coverage, research-data write, candidate activation, API/UI readback, or natural-slot retry was established. These remain `CANNOT_CONFIRM`; this PASS covers only the frozen candidate and its synthetic guarded behavior.

**Overall:** PASS for the frozen R3 candidate's review and synthetic behavior. This receipt does not mark the candidate activated, deployed, or naturally verified.
