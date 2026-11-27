# ACT-078A Mac research replay

V2.2 scores first independent waves from the frozen V2.1 stock and date keys. The 41 stock chains and SSE come from ACT-074. The frozen comparison ends on 2026-11-20. The raw histories extend through 2026-11-26 and provide the observable outcome horizons. The four later trading dates have no frozen comparison keys.

Use the approved original artifacts in a run's `sources/` directory. The driver checks ZIP contents, manifest identities and roster membership. The pre-OOT dataset consists of 2,708 frozen trigger rows through 2024. It uses historical raw bars only for calculation and keeps the canonical V2.1 episode and anchor identities.

## Stage order

Run from the V4 source root using the absolute `PANEL_PYTHON` runtime. The fit claim permits one invocation for the given research run. A separate exclusive claim permits one OOT opening.

```sh
"$PANEL_PYTHON" -B ops/pft_act078a/task.py prep --artifact-root "$ACT078A_RUN_ROOT"
"$PANEL_PYTHON" -B ops/pft_act078a/task.py fit --artifact-root "$ACT078A_RUN_ROOT"
"$PANEL_PYTHON" -B ops/pft_act078a/task.py oot --artifact-root "$ACT078A_RUN_ROOT"
```

The prep receipt records D-only parity, prefix tests and per-fold maturity. All five OOF holds use chronological group boundaries, with earlier mature first events for each training fold. The initial 217 Train events supply warmup. The four fixed families each use five OOF fits and one full Train refit, for 24 total fits and zero tuning under the user-authorized budget. The family predictions are stored in `run/pre_oot_scores.parquet` and the refit estimators in `run/weights/`. OOF estimators were transient. The frozen splits, configuration, environment, seed, score output and fit journal preserve the OOF replay inputs.

The Val rank lock averages family scores within each axis, converts axes to Val percentiles and applies frozen A and A/B coverage cutoffs. OOT checks hashes for the code, data receipts, fit journal and weights before scoring. Its ledger retains confirmation, repeat, warmup and maturity states. The primary metric comparison uses the common scored first-event universe. Each selected set uses the same per-horizon maturity rule and 30 bp fee.

## Atlas outputs

The renderer uses separate chart manifests for the D-only and post-event PDFs. It requires ReportLab, pypdf and a CJK TrueType font. Set `ACT078A_CJK_FONT` if the default macOS font path is unavailable.

```sh
"$PANEL_PYTHON" -B ops/pft_act078a/render_atlas.py "$ACT078A_RUN_ROOT/run" "$ACT078A_PDF_OUT" 20261127
```

Keep the D-only PDF with the blind review. Release the post-event PDF for review after the blind assessment is locked. The replay package contains scoped evidence, weights and full pair analysis. `RESULT.json` records the aggregate decision and run identities for the source repository.
