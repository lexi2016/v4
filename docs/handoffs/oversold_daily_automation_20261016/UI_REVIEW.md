# Rendered V4 UI verification

UI_VERIFIED=PASS for controlled recovery output. Root reloaded http://127.0.0.1:8873/manager-selection/?date=20261016 in the existing browser, selected the OVERSOLD recommendation and applied the strict-selection filter.

The stable rendered page identifies run `c1c5e85d691c46f98086b74053fe8ff8`, target date 20261016, phase NEXT_DAY (display label 16:30 next-day draft), and both cutoff/generation at 2026-10-16 03:34 Hong Kong time. The phase label does not mean this run occurred at 16:30. Lane status remains PARTIAL.

The complete lane counters are 21 SELECTED, 171 CONDITIONAL_WATCH, 124 UNASSESSED, 0 OBSERVATION_ONLY, and 373 NOT_SELECTED: 689 total records. The strict filter renders 21 data rows plus one header. The visible first selected stocks include HK.00100 MINIMAX-W, HK.01347 华虹宏力, HK.01377 鼎泰高科 and HK.01384 滴普科技, with saved source-session 20261015 and rule explanations.

Plan history visibly retains the failed automatic recovery `0c72d7ade78249d280b03418e71db681`, the earlier manual runs `5cb9b603e183428cab8de8990abcb7e3` and `04fd6d63b3bc4a9e8fabe7a481c12d4c`, and legacy NEXT_DAY `18425e50e6294f15a6bc02ac881c5af2`. The UI shows RESEARCH_ONLY=true and production_allowed/buy_gate_updated/orders_sent=false. No UI action generated a new plan.

The initial 0c72 run was separately observed as 689 UNASSESSED with TDXPY_EXACT_HISTORY_UNAVAILABLE; that was a failure and was not accepted. This later result closes the rendered-output check after cache-first repair. Natural post-close daily execution has not yet occurred and is NATURAL_SLOT_UNVERIFIED; this UI receipt is not natural-slot acceptance or investment validation.

Screenshot: `oversold_daily_live.jpg`; SHA256: `af6d44c144c044000352b47ad1cadcdd1b79de730f7cd9330a73392a1a608b6d`.
