# R2 Mac independent acceptance — 2026-09-30

Input: PR #9, immutable head e9b91cc9e27aa5e3360d03040529d6ba164a6fe4. This evidence directory is a sibling of the original package; its 69-file manifest is unchanged.

## Accepted scope
- Frozen combined R1+R2 candidate has 1086 files. Exactly one source path differs from frozen R1: v4/manager_research/connect_selection.py.
- Independent reviewer: PASS_WITH_P2_FOLLOWUP; P0=0, P1=0, P2=1.
- Independently rerun against the actual isolated candidate and target Python 3.14.6: R2 27/27 and affected R1 47/47 pass. Import probe and JUnit receipts are in reviewer/.
- BEHAVIOR_VERIFIED applies only to synthetic read-side binding/diagnostic behavior and these regressions.

## Unresolved target acceptance
At 2026-09-30T14:07:13.393122+08:00 both explicitly compared roots lack universes/20260930/HK_CONNECT_FULL_MARKET.json. Original reader returns HK_CONNECT_EXACT_UNIVERSE_MISSING; network_requests=0, data_writes=0, activation_allowed=false. This is not a whole-project absence claim. No deployment, binding activation, real API/UI acceptance or natural-run acceptance was performed.

## Existing owner and next bounded delivery
Read hk_connect_source_owner_trace_20260930.json for 24 path/SHA evidence entries. The configured scheduler candidate contains enabled 16:08 close and 17:20 daily HK jobs, both reading Futu HK.GangGuTong and HK.LIST1922. The same-job seam closest to the shared authority root is owner v35_dispatcher.research_panel_daily_hk (17:20), which already captures data and invokes ensure_hk_security_master.

Current configuration points to a release whose manifest says NOT_ACTIVATED/CANNOT_CONFIRM. The last confirmed successful artifacts are 2026-09-28 under an older release; they cannot prove the configured candidate ran successfully. Existing capture retains normalized union/filtered quote rows, not original per-plate responses or query timestamps. Security-master captured_at is publication time.

Next implementation must:
1. Resolve the canonical V4 source-to-current-release owner binding; do not patch an unowned release snapshot.
2. In the existing collector and same provider calls, retain per-plate membership before normalization/dedup, with acquired_at, capture_run_id, row count and SHA.
3. Reuse existing capture/publication flow for the approved exact-universe contract and authorized root. Validate original-reader schema and availability/cutoff semantics; do not invent timestamps or treat same-day post-close data as earlier available.
4. Independently verify published membership and then the real announcement/US-mapping API/UI cases (including 09969/LLY). No new producer, additional duplicate fetch, disabled legacy Stage full-market path, or Vibe 8910 changes.

## P2 follow-up
R2-P2-STALE-OWNER-BINDING-DIAGNOSTIC: holding date/codes/artifact SHA fixed while changing the owner-code pin may reuse a saved plan whose selection_diagnostics still shows the prior pin. Independent synthetic reproduction is reviewer/p2_saved_diagnostic_repro.json. Live occurrence CANNOT_CONFIRM; no pool-widening or BUY effect shown. Refresh current diagnostics or include binding in the relevant identity, with a changed-pin saved-plan regression. This exceeds the frozen one-file increment and belongs in the next scoped change.

## State
IMPLEMENTED/TESTED/REVIEWED: scoped candidate as above.
INTEGRATED: isolated candidate only.
DEPLOYED/API_VERIFIED/UI_VERIFIED/NATURAL_VERIFIED: not established.
Manager remains HK_CONNECT-only. RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.
PR #9 remains Draft/unmerged; Issue #8 remains open.
