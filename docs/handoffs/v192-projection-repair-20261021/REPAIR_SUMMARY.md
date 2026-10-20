# V192 canonical projection repair

The active daily increment computed canonical outputs but dropped16 of the17 required fields and overwrote canonical ref_hold_score with a four-term approximation. The maintained payload now projects all17 required canonical outputs, preserves their values, and rejects missing/nonfinite required fields as an authority failure before schema defaulting. Formula arithmetic, thresholds, CPOS, and other three excluded fields are unchanged.

This is an exact maintenance copy of the existing producer, admitted into the V4 branch; it does not introduce another running producer. Origin SHA901d4802c784decda9d43e757b367496d1171e5e702485a29f4c66fad3c7ae2e; repaired SHA57ce8ea5e629398cddea3e943dc98aa8f6c4caa241732294403d2ccf0033b6ba. Baseline55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054; branch codex/v192-projection-repair-20261021. Existing main-checkout untracked candidates were preserved.

Required17: kdj_d; ref_score_close_up/ref_score_above_bbi/ref_score_no_giant_true_yin/ref_score_trend_up/ref_score_j_no_dead_cross; ref_hold_score; brick_original_b1/brick_pullback_white_b/brick_pullback_yellow_b/brick_oversold_shrink_b/brick_oversold_super_shrink_b; brick_strong_red/brick_red_today; macd_above_zero_second_gold/macd_top_divergence/white_yellow_death_cross.

Writer validation: one registered synthetic260-row module canary passed, then21 further regressions passed without repeating that canary. The two-symbol520-row regression compares every required value exactly with the pinned canonical pure function and every non-target output with the original producer.17 missing-column cases and3 nonfinite cases fail closed. Source/test/config and deterministic synthetic fixture generator were frozen before execution. No market input, labels or network was used.

Independent SolHigh review passed the actual3-hunk change and all22 unchanged synthetic assertion cases once, using the stdout-only command in REVIEW_COMMAND.md. Fixed V4 Python3.14.6 is required for AST serialization identity. Reviewer receipt: REVIEW_RECEIPT.json. Scope status=REVIEWED/PASS/BEHAVIOR_VERIFIED for synthetic17 projection only.

No runtime path, release, service, data, pointer or scheduler was changed. Real3 historical compatibility is a separate registered engineering gate and is not certified here. No production/trading permission changes: research_only=true, production_allowed=false, buy_gate_updated=false, orders_sent=false. Git publication is delegated to controller and unverified at this document's creation.
