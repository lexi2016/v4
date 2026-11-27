# ACT-080 Phase 2

Use the pinned P1B worktree base, signed run root and separate verified runtimes.

```sh
"$PANEL_PYTHON" -m ops.pft_act080_p2.prep --run-root "$RUN" --vol2 "$VOL2"
"$PANEL_PYTHON" -m ops.pft_act080_p2.fit --run-root "$RUN" --mps-python "$MPS_PYTHON"
"$PANEL_PYTHON" -m ops.pft_act080_p2.open_oot --run-root "$RUN" --vol2 "$VOL2" --baseline "$V21_ARCHIVE" --mps-python "$MPS_PYTHON" --expected-lock-sha256 "$REVIEWED_FIT_LOCK_SHA"
"$MPS_PYTHON" -m ops.pft_act080_p2.render_case --run-root "$RUN" --expected-release-sha256 "$ISSUED_SHA" --pdf "$CASE_PDF"
```

Prep verifies signed bytes and projects only authorized TRAIN/VAL FIRST rows and price prefixes. The eligible roster has 40 securities. The 19 and 24 column matrices omit identities, dates, outcomes and fold assignments. Label maturity is per outcome and within the applicable timeline. The MLP normalizer estimates use only rows that supply gradients, and its held-out TRAIN suffix observes the 10-session purge and embargo.

Fit verifies the prepared seal, writes a durable dispatch and start record for each model, and binds all successfully fitted weights, normalizers, validation scores, thresholds, eight candidates and exact selected-model reload. The selection score is one minus predicted standard tail probability. Quantiles and coverage use all VAL scores, with an additional 60 selected mature standard-tail floor. The model sees neither OOT nor Junda values before lock. Use `fit --ledger-only` after interruptions to materialize existing attempt records, with no fitting.

After the exact lock SHA and source bytes verify, the opening stage claims both holdouts with an exclusive file. Keep the claim on every failure. Package issued outputs or available partial evidence without rerunning the opening command. The exclusion matches all 72 signed identities by exact dates in the stock-observed clock. A missing ordinal fails closed. The baseline is frozen Grade A among earliest archived FIRST identities and is carried alongside the all-FIRST diagnostic. Both Clean OOT policies use the same exclusion and split rules. Their event support differs. Junda case rendering uses only the issued checkpoint. All outputs are research only.
