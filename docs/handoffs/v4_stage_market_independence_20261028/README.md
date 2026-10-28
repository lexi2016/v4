# V4 A/HK stage selection continuation — 2026-10-28

This handoff records reviewed source and the actual Stage-only local deployment. Main hourly/name and API name updates remain pending. It preserves the two-market research-only boundary: `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.

## Recorded problem

- On 2026-10-28 the 08:30 and 09:00 hourly research source was PARTIAL after the 20-page per-source limit. The old reader/executor rejected the whole source; A research-context failure then entered shared Stage error handling and prevented an independent HK selection. HK input rows did not by themselves prove a selection.
- On 2026-10-27 the 08:30 original fetch also had unfinished pagination, but its then-running producer marked nonempty topics READY and reused that early timestamp as the 09:00 window start. The naturally dispatched 09:35 stage produced 10 A and 10 HK rows, both PARTIAL. This does not establish full source or PIT validity.
- On 2026-10-22 A 09:25 rows used 09:26:37 transaction recovery. On 2026-10-27 and 2026-10-28 native A 09:25 capture rejected future-dated quotes. Do not present recovery as natural 09:25 capture.

## Reviewed Stage source

`stage_source/` is the exact two-file overlay independently reviewed against the installed Stage baseline; `tests/` contains its frozen tests. The isolated reviewer ran 8 integration tests successfully and reproduced both market directions and HK input OSError isolation. A shared bundle-write failure can still leave both markets unconfirmed. See `LIVE_STATUS_20261028.json` for the later local deployment and manual late-replay readback. The source test itself is not natural-run acceptance.

The initial control-readiness FAIL is retained. The later R4/R6 control reviews passed for exactly two known calendar-only Stage labels in a finite trigger-empty window, with the original owner guard, source/plist/metadata CAS and protected data/service checks. R4 activated at16:22 and R6 corrected the legacy launcher PYTHONPATH at17:15:44. `control/` is frozen control source, not a reusable live plan. Never run old or expired plans.

## Name coverage

R6/R7 source candidates, frozen tests and independent reviews already exist on the parent branch under `docs/handoffs/v4_business_gaps_20261027/`. Their exact SHA values were rechecked and their current Main/API integration was tested only in isolated copies. They are not installed. Current unattended BJ identity coverage remains unconfirmed.

## Hourly-source continuation

`hourly_candidate/shared/` contains source needed by both Main and Stage; `hourly_candidate/main/` and `hourly_candidate/stage/` contain role-specific files. The R3 writer and independent reviewer tested the original executor through materializer, source-only refresh, scheduler ledger and cross-release Stage in isolated copies. Independent review passed after two R2 findings were repaired. This does not authorize publication or establish live acceptance. The local scheduler ledger is a consistency chain, not an externally signed timestamp. Missing historical completion evidence remains unverified.

The Stage release and two Stage labels were activated locally; Main/API/collector were unchanged at this snapshot. Six failed intraday slots were replayed using preserved raw inputs. These are late recoveries, not natural/PIT proof. API readback verifies10 HK rows in all8 slots; A inputs remain unconfirmed. Original receipts and raw data are preserved. No trading gate or orders changed.


## R7 prepared, not active

`control/r7/` contains the exact reviewed Main/API/Stage control source and targeted tests. R7R1 closed the initial recovery P2: both role checkpoints precede the root helper and completed owners are revalidated. The terminal-owner R2 condition preserves a FAILED daily receipt; it never certifies successful data. Host-bound plans and runtime directories are intentionally absent. Tests were executed in the original scoped CASE, not claimed as portable CI checks.

Three exact release directories have been copied and verified locally (Main884/API1329/Stage983 files) but no R7 label is activated. The user has agreed to one-time local terminal authentication; actual authentication and an idle/fresh owner boundary remain required. Existing daily data computation/retries continue naturally.

A-share historical gaps remain unresolved as formal selections. Original09:00 natural tasks both FAILED/INPUT_MISSING and did not create incoming input, archive or hourly publication; readable raw topics have no bound historical completion. Later R7 activation cannot retroactively supply those old cutoffs. See `A_SHARE_HISTORICAL_INPUT_BOUNDARY_20261028.json`. Do not present existing preselection candidates as recovered stage selections.
