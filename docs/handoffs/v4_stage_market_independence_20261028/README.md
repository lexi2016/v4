# V4 A/HK stage selection continuation — 2026-10-28

This is a source-and-evidence handoff, not an installed release. It preserves the two-market research-only boundary: `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.

## Recorded problem

- On 2026-10-28 the 08:30 and 09:00 hourly research source was PARTIAL after the 20-page per-source limit. The old reader/executor rejected the whole source; A research-context failure then entered shared Stage error handling and prevented an independent HK selection. HK input rows did not by themselves prove a selection.
- On 2026-10-27 the 08:30 original fetch also had unfinished pagination, but its then-running producer marked nonempty topics READY and reused that early timestamp as the 09:00 window start. The naturally dispatched 09:35 stage produced 10 A and 10 HK rows, both PARTIAL. This does not establish full source or PIT validity.
- On 2026-10-22 A 09:25 rows used 09:26:37 transaction recovery. On 2026-10-27 and 2026-10-28 native A 09:25 capture rejected future-dated quotes. Do not present recovery as natural 09:25 capture.

## Reviewed Stage source

`stage_source/` is the exact two-file overlay independently reviewed against the installed Stage baseline; `tests/` contains its frozen tests. The isolated reviewer ran 8 integration tests successfully and reproduced both market directions and HK input OSError isolation. A shared bundle-write failure can still leave both markets unconfirmed. This is not a deployment or natural-run acceptance.

A separate control-readiness review was FAIL: the archived Stage-only proposal is not executable, and a point-in-time idle PID does not close the admission race before launchd bootout. Do not run the old multi-service controller or its review-only plan.

## Name coverage

R6/R7 source candidates, frozen tests and independent reviews already exist on the parent branch under `docs/handoffs/v4_business_gaps_20261027/`. Their exact SHA values were rechecked and their current Main/API integration was tested only in isolated copies. They are not installed. Current unattended BJ identity coverage remains unconfirmed.

## Hourly-source continuation

`hourly_candidate/shared/` contains source needed by both Main and Stage; `hourly_candidate/main/` and `hourly_candidate/stage/` contain role-specific files. The R3 writer and independent reviewer tested the original executor through materializer, source-only refresh, scheduler ledger and cross-release Stage in isolated copies. Independent review passed after two R2 findings were repaired. This does not authorize publication or establish live acceptance. The local scheduler ledger is a consistency chain, not an externally signed timestamp. Missing historical completion evidence remains unverified.

No runtime release, config, user data, service or trading action is performed by this handoff.
