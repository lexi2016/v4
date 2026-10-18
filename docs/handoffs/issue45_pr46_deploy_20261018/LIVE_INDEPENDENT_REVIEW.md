# Issue45 live independent review

Reviewed at 2026-10-18 11:17 HKT by `issue45_deploy_review`, read-only, within the frozen Phase 3 acceptance scope. This receipt records live identity and current owner-to-manager evidence; it does not close Issue45.

## Gate verdict

- `DEPLOYED`: **PASS**. The named live LaunchAgents were bound to the reviewed immutable candidates: digest `issue45-pr46-us-digest-20261018-r2` (manifest `73db17d4a3d8af900f00ca056716a20f289b4df90b5f862d1207790f1a18e201`, plist `cd5cf69b83f4b576eaed552dfe004dd4d01e3cf69393f057c42ba6c92ff34930`); manager `issue45-pr46-manager-scheduler-20261018-r2` (manifest `58e3f267ce1fec7af8104df379378a6f0b234faa2b6453174a12681ea0226969`, plist `15c6065528e8376fe9f094f2a9c67e99df6c2bc4acb20c11574e521edf37e8a1`); API `issue45-pr46-api-20261018-r3` (manifest `40872d5013f2239b40821f8547e65bcfed0af58102efb16113a38f2f5bc401e9`, plist `27b613a9a4ca52fc30e60d4ce5510974d3647fdf574966ab2f24cb930146c653`). Runtime CWD/identity and source SHA checks were performed after activation; API PID was 20615 at candidate r3 and manager PID was 21161 at candidate r2. Digest loaded idle with zero captures kicked by activation.
- `API_VERIFIED`: **CANNOT_CONFIRM**. The configured current owner root has no valid US20261016 → HK20261020 input. The session-date fallback is bound but belongs to US20261015.
- `UI_VERIFIED`: **CANNOT_CONFIRM** for the target result. The reloaded API/UI agree on the existing target-20261020 plan `5feb2dbf6d3c4b6b8598e9dae67af542`, generated 2026-10-16 17:39 HKT, with source US20261015 and `US_MAPPING=INPUT_MISSING`; agreement on this historical plan is not a refreshed target result.
- `BEHAVIOR_VERIFIED`: **CANNOT_CONFIRM** live. The frozen offline candidate checks passed, including manager handoff 4/4 and API focused 13/13; the deployed manager has no current valid US16 identity to exercise. The offline catalog conservation result remains 667 catalog stocks and 1,003 relations, with catalog relations `CANNOT_CONFIRM` / `CATALOG_OBSERVATION_ONLY`, outside the fixed-33 denominator.
- `NATURAL_VERIFIED`: **CANNOT_CONFIRM / NATURAL_SLOT_UNVERIFIED**. The next natural input is POST_CLOSE US20261019 → HK20261020 at 2026-10-20 04:15 HKT. The earlier US20261016 historical catch-up remains a separate, unproven item.

## Exact owner and handoff evidence

The deployed API binds `us_root` to `/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data` (`V35_DATA_ROOT` in `com.lexi.v35.api-only.plist`, passed as `store.root`). The manager scheduler uses `/Users/lexi/Library/Application Support/com.lexi.v4.local/config/manager-workbench-v7.json`; that config binds the same `us_root`, `state_root=/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench`, and `dynamic_source_bindings=true`.

For the exact target-date lookup, both `/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data/research/peripherals/20261020/external_finance.json` and `/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data/receipts/research/peripherals/20261020/external_finance.json` are absent, and the owner manifest has no target-date artifact binding.

The configured session-date fallback exists and its artifact SHA is manifest-bound:

- Artifact `research/peripherals/20261016/external_finance.json`: SHA-256 `fedb7f6f3b993d460ae029158bf73748f6205a23802395ccd8b2a642601be7ae`.
- Receipt `receipts/research/peripherals/20261016/external_finance.json`: SHA-256 `2070193eb102cd82f09a83deb5cf486a0adf086ec388f749f6c726dce2be5f23`.
- Owner manifest `research/peripherals/manifest.json`: SHA-256 `97b478fb8afe0f6ba87e69261c150f7d1f2ff3ff92601185e91b85998677111e`.
- Payload says `capture_phase=POST_CLOSE`, `capture_session_date=20261015`, `captured_at=2026-10-16T07:41:53Z`, 48 requested and 48 available quote symbols. Receipt says `trade_date=20261016`, `us_session_date=20261015`, `source=external_finance`, `payload_path=research/peripherals/20261016/external_finance.json`, and payload SHA matching the artifact.

The deployed consumer therefore rejects the fallback for the requested session with exact typed gap `US_OWNER_RECEIPT_ARTIFACT_SESSION_INVALID`. This is not a valid US20261016 owner artifact. Its 48/48 quote rows are for US20261015 and do not establish current-session coverage.

The manager’s configured store is `/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench/manager_workbench`. A scoped read of its `cursors/us_close_*.json` records found zero target-20261020/session-20261016 matches. The only `catalog/20261020/NEXT_DAY` records are runs `5feb2dbf6d3c4b6b8598e9dae67af542` and `85bec0f938224cc4ac92be7dbefcb2df`; both have source US20261015, `US_MAPPING=INPUT_MISSING`, and no `us_close_handoff_key`. Handoff state for the exact US16 identity is **absent**, not consumed or pending. Because no valid US16 input exists, this evidence does not show an unconsumed-existing-input regression.

The fixed-33 coverage metric remains distinct from both the 48 quote rows in the stale US15 artifact and the 1,003 catalog observation relations. This narrow owner check does not recompute the 4/33 coverage result (`CANNOT_CONFIRM` here); none of those counts is substituted for another.

## Unrelated 11:00 failure and safety

Manager receipt `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/dispatcher/receipts/live/20261018/1100/f10afb17a7f343f1a7ca057c689d08dd.dispatch-receipt.json` (SHA-256 `ba7f340192e1e9239531b9c7abe9883b472133f7f59744100d9add2b46a15448`) records a Sunday `hourly_research` failure: `UPSTREAM_NOT_READY`, `HOURLY_RESEARCH_INPUT_NOT_MATERIALIZED`, no US session/eligible market, and no workload start. It is not an Issue45 US POST_CLOSE dispatch; no rollback is indicated by that receipt.

Safety remains `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false` in the reviewed runtime/receipt evidence. No source data was written, replayed, or recaptured during this review.

## Findings and remaining acceptance

No P0/P1 code regression is proven by the reviewed live evidence. Acceptance is blocked by the exact upstream owner-session mismatch above. The Sunday hourly failure is a separate fail-closed input gap. The natural slot, current target plan, and downstream current-date display remain unverified until a valid owner artifact/receipt for the required session is naturally produced and consumed, then read back through API and refreshed UI.
