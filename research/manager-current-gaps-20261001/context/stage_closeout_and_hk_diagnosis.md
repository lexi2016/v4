# A-share closeout and bounded HK failure diagnosis

User scope: close A-share work now; diagnose HK failures only, without continued repair. No further business code/configuration/service/data changes are authorized in this closeout.

## A-share closed

- Ordinary Stage API matrix confirms 21/21 applicable A-share date-stage cells have rows over 20260928–20260930: `after_a_recovery_api_matrix.json`.
- Newly recovered 20260929/30 A0925 and A1445 each have 10 WATCH_ONLY rows. The original ordinary pointers and old failure records remain preserved. Recovery is partial, not full-source or natural-time acceptance.
- A0925 source/composition and actual runs independently verified. Receipt: `../review/stage_a0925_20260929_30_actual_runs_review_20261001.md`, SHA256 `daf2b58a743f515a3a3b85b9642f6261fe105f7ad130153d06a27dc571487c28`.
- Ordinary UI checked for both dates and stages; screenshots are beside this document. Stage binding remains `20261001-stage-pr16-a1445-a0925-crossday-r1`; API reader/UI binding remains `20261001-stage-consumer-visibility-r1`.
- No additional A-share edits or tests planned. Natural-time and complete-source acceptance remain CANNOT_CONFIRM.

## HK failures are distinct

| Date / path | Confirmed evidence | Limit |
|---|---|---|
| 20260928 | Old D1 price signal_date=20260924, while previous HK-securities session is 20260925; actual preselection policy used A-or-HK-Connect admission and skipped HK-only days. | Existing rows do not prove corrected-price-session acceptance. |
| 20260929 A1445 recovery | Original runner reports PyTDX ExHQ probe execution failed / returned error, completed=0/100. | Underlying provider exception is not present in this receipt; no network/server/root-cause claim. Other missing stages must not automatically be assigned this same cause. |
| 20260930 A1445 and A0925 recovery | HK D1 status must be STRICT_0_2_READY; exact prior-date9/29 source/D1 is unavailable. | The gate failure is verified; the underlying9/29 collection failure is not established by these receipts. |
| 20261008 future-path validation | Required9/30 authority pointer missing; exact-price-panel fallback689 vs captured master696 causes reuse rejection. | This is a separate future-path blocker, not the cause of every September failure. |

## Verified authority/master mismatch

Actual scheduler uses V35_HK_UNIVERSE_ROOT `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data` and shared-data store `.runtime/data` beneath it. The missing expected authority is `universes/20260930/HK_CONNECT_FULL_MARKET.current.json`. Read-only diagnosis found no matching pointer in the checked active V35 state; no evidence establishes a root-directory mix-up.

Only the specific missing-pointer error triggers the existing exact-day price-panel fallback. That panel yields689 codes with canonical SHA256 `33215df7fd109cba5597f9d4f920e5887e5856f2fa23c7328b8cb597b50332c2`. Verified security-master run `49ffde1ebebdc85e4680e701` has696 rows, captured2026-09-30T17:20:08+08:00, universe SHA256 `162fb3ec7f50a1130f202be9d39461218260e57cc9b1cefb279d629828885e09`; artifact SHA256 `754794679937494dc8dc6cdc8dfbd14dfa4b070ea709f551874e39006aa712dd`.

Writer read-only diagnosis traced `state/research_panel_daily/receipts/hk-20260930.json` and its capture manifest/raw:696 captured/master rows,689 valid price-volume rows, with the seven master-only codes excluded for non-positive OHLC/turnover/volume. Thus the difference is security membership versus usable price coverage, not evidence that seven master members are invalid. Neither count alone establishes canonical HK_CONNECT authority.

Independent r2 review: `../review/hk_calendar_policy_lane_delta_r2_independent_review_20261001.md`, SHA256 `16002ef24bfa64e8ffba23e1f8208267a944bf50b6e88f96eed8bac59cef73d5`. It records20 focused tests passing but real-source P1 unresolved, plus A-artifact-retention test coverage gap. No opening readiness claim.

## Stop and handoff

A-share repair is closed. HK diagnosis is complete at the evidence level above. No further edits, source capture, service changes, or external-source search will be performed in this batch.

HK r2 source changes and partial inactive app/shared-package/Stage candidates are preserved but not activated; they are not deliverable runtime releases. Active V35 scheduler and shared package remain unchanged. A later authorized repair should restore/validate the dated full-membership authority through the original contract; never substitute the price panel for membership, accept a master solely by row count, or backdate a new capture.
