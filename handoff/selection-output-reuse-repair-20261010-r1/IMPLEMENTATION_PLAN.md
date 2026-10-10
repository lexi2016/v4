# V4 selection output reuse — implementation plan

> For agentic workers: execute inline under superpowers:executing-plans; verify the whole delta independently before publishing it.

**Goal:** repair only source defects reproduced against the frozen handoff, preserve the original successful announcement owner chain, and make the remaining real-input blockers actionable.

**Architecture:** use the supplied current release modules; the historical daily announcement runner remains the existing CLI, with its successful register-handoff path as reference. No additional producer or alternate stock-selection algorithm.

**Spec:** fixed commit e72607634d46146b0b6c0f4a0396f6b2939589f7, handoff/selection-output-reuse-issue-20261010-r2/README/CHAT_HANDOFF.md

**Tech stack:** Python, original ManagerResearchStore/FastAPI routes/validators; synthetic source fixtures only in isolated tests.

## Global constraints

- Exact target 20261009 / publication 2026-10-08; keep historical target 20261008 / publication 2026-10-07 separate.
- Preserve RESEARCH_ONLY=true, production_allowed=false, buy_gate_updated=false, orders_sent=false.
- Preserve current/historical source provenance, cutoff/owner/date/market/SHA/full-input validators and original numerical selection rules.
- No new capture, fabricated reviewer outputs, copied real other-day selections, formal Stage changes or natural-run claims.
- Real production selection remains unverified without the current original owner inputs and live Mac readback.

## Review focus

- Receipt addition must precede final base identity used by stock_selection; direct build must equal register-handoff for identical inputs.
- Selected, watched, not-selected and no-decisions cases must retain their meaning.
- Altered dates/receipt/source SHAs must fail before writing output; existing different output remains protected.
- Decimal equality at exactly 80 percent must pass; values immediately above must fail without epsilon tolerance.
- Missing volume unit/scale authority must keep oversold rows pending after the arithmetic correction.

## Task 1: announcement reviewed build

- [x] Add regressions using the original source-backed synthetic handoff fixture and full application validators.
- [x] Observe base-product SHA failure in the original build-reviewed branch.
- [x] In ops/run_manager_daily_announcement.py, rebuild the original selection extension after binding the verified review receipt, as register-handoff already does.
- [x] Verify equal product hash and original owner API/analysis/workspace readback; reject wrong dates, tampered receipt and overwrite.

## Task 1b: reuse existing CLI readback compatibility fix

- [x] Reproduce valid current owner receipt rejected by old projection-as-product stub.
- [x] Reuse _readback byte-for-byte from the same commit's existing manager-three-channel-repair-20261009 candidate and its existing complete validator import.
- [x] Add 10 real-route synthetic regressions: modern receipt, eight altered chains, and preserved legacy receipt bytes.
- [x] Record reference source/function SHA and retain date, receipt, handoff and cutoff validation.

## Task 2: oversold boundary

- [x] Add actual read_rebound_screen boundary regressions with explicitly synthetic unavailable owner boundaries.
- [x] Observe equality failures for 0.28/0.35 and 0.56/0.70 in the original.
- [x] Reuse existing Decimal comparison policy for close <= 0.8 * prior60_high; use the same threshold in explanation/near-distance fields.
- [x] Verify above/below/equal/missing cases and unchanged pending volume gate.

## Task 3: delivery and real-input continuation

- [x] Run supplied 17 announcement tests plus all 25 new targeted tests; record support-only dependency provenance and environment limitations.
- [x] Independently review the minimal two-file delta and real-input instructions.
- [x] Deliver before/after SHA, full after files, exact patch, tests, apply/rollback steps and precise original-owner evidence request.
- [ ] Publish to a new GitHub branch based on e72607634d46146b0b6c0f4a0396f6b2939589f7 and verify remote bytes. Publication is the final step after this package is frozen; the final chat provides the observed commit and readback result.

## Rulings and progress

- The handoff is a source snapshot, not a full Git checkout. Work/app is an isolated assembly; no current user worktree is being modified. Frozen remote commit and each file hash are the baseline.
- GitHub support modules omitted from the ZIP are test dependencies only. They are not replacements for deployed source identities and will not be shipped as runtime changes.
- HK_CONNECT and Stage investigations found no incident-causing consumer defect; do not modify those paths based on synthetic malformed envelopes.
- None of the three discovered code defects proves the current live incident's full cause. Current exact announcement product, V2 authority, attested volume history and Stage artifact still require owner readback.
