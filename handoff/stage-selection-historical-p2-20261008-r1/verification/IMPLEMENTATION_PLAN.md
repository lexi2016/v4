# Issue #28 continuation — three registered historical P2s

## Fixed boundaries

- User requested continuation after the completed source handoff at `d8485e92bed685a1dc38a1f40a05858b9be4765c`.
- Fresh Issue #28 readback still has zero comments and the repair branch remains at that commit. No new Mac acceptance has been supplied.
- Preserve all R1 source, package, review and archive bytes. Do not treat the parallel `4c5097348713b2793611dbcf0d116c69229ecb2f` candidate as a Mac result.
- New work is confined to the three P2s already recorded in frozen Issue #28 evidence, section 7. No data restoration, live service or deployment claim.

## Investigation and decision gate

1. Reproduce source-date upper-bound acceptance against frozen `infrastructure/preselection_pool_store.py`. The supplied requirement is source dates no later than target date, not a new calendar or strict D-1 policy.
2. Derive nested provenance fields from pinned existing schema/producers, with required and optional fields separated. Do not invent a whitelist for open input-hash maps.
3. Reproduce missing source/PIT uncertainty in `ops/build_close_review.py` against the real supplied review contract. Avoid a date-specific patch; preserve corrupt-source exceptions and exact missing sentinel behavior.
4. An independent reviewer checks compatibility boundaries before code edits. Only implement changes supported by concrete original contracts and red probes.

## Implementation and validation

- Each author works in a separate new directory under `work/continuation_1325`.
- Keep exact before files, minimal after differences, red and green logs, focused unchanged regressions, and pinned test support identities.
- Test same-date and split-date provenance, late-capture recovery, expected dynamic hash-map keys, legacy provenance absence, real store readback and immutable original artifacts.
- Do not rerun unchanged R1 suites or count prior historical PASS totals as new executions.
- Conduct one bounded final independent source review, close material findings on exact final hashes, and replay patches in both directions.

## Delivery

- Add a new historical-P2 handoff directory on a new branch based on the completed R1 commit. Do not edit old frozen handoff paths.
- Include exact before/after SHA, actual environment, commands, minimal support and logs, Mac adaptation/rollback instructions and remaining evidence gaps.
- Verify remote commit/tree and changed file contents. Produce and verify a downloadable incremental archive if changes are supported.
- If a P2 lacks a defensible contract, record the precise missing evidence and retain that P2 instead of fabricating defaults or source identity.
