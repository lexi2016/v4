# ACT030 continuous features and same-exam scaffold

This research-only implementation performs no training, model loading, prediction,
production changes or panel writes. `pft_act030_features` consumes an explicitly
bounded history ending at D. Future bars, duplicate dates and nonfinite inputs
fail; insufficient windows or unavailable anchors produce nulls.

The sixteen values are ordered in `GROUPS`: five anchor distances, five volume
ratios, four shape values and two close/line distances. All percent distances
are ratios minus one. Anchor ATR distances use simple ATR20. Public active low
and midpoint hints are explicit inputs; invalidation defaults to that active low,
without a buffer. The root low comes from its dated bar. Anchor dates without
an observed D-or-earlier bar fail closed. The normal feature function accepts
`Anchors`; the separately named reference function is diagnostic only.

The platform is mean volume in `[-25:-5]`; the wave peak is the mean top three
volumes in `[-35:-5]`. Contraction uses the last three-bar mean; D/platform uses
D volume. Down-volume is the maximum C<O body volume in the last five bars
(zero if none). Up-volume purity is volume on C>previous-C days divided by all
last-20 volume. These two candle conventions are explicit candidates; publication
residuals remain unresolved. Box width is `(max H-min L)/mean C` over 5/10 bars.
Convergence is `(OLS slope L15-OLS slope H15)/mean C15`. ATR contraction is
simple mean TR5/TR20; true range includes gaps to the previous close.

The verifier pins ACT022's archived V4 Backtest generation and its immutable
factor snapshot. It compares every public bar/field using the original `.16g`
serialization and separately reports raw floating differences. D-basis repair
undoes only already-baked post-D price transforms, newest first, for OHLC and
white/yellow/BBI; volume uses its independently supplied factor, while raw CNY
amount is retained. There is no clipping. D-basis results are withheld when any
chosen raw alias has a missing, incomplete or divergent event timeline compared
with the canonical symbol; mixed old/new alias windows cannot borrow a different
canonical adjustment ledger. The later snapshot establishes a
normalization audit, **not historical PIT certification**. Three raw-source
canaries use the existing owner's resolution/formula methods with only
pre-D-or-D events and observations.

`pft_act030_eval` joins frozen labels and already supplied scores by exact IDs.
Current CLI labels are restricted by SHA to the approved ACT026 calibration100.
A future whole240 path requires a separate explicit release receipt binding
actual 240 labels, predictions, baseline and file hashes. It has no decryption
or key-handling path. Baseline-only mode retains the ACT026 score arithmetic;
challenger mode reports both baseline LR/RF raw/gated and supplied challenger
raw/gated values on identical rows. Baseline binary gating is checked; challenger
gating has its own explicit contract (`provided_scores` or `binary_zeroing`).

Primary metrics use unanimous POS/NEG/EVENT (EVENT is binary negative), with
POS/NEG secondary. Threshold is >=0.50. Ties sort by episode ID, with tie ranges;
P@20/30/50 are null below K. Recall, F1, AUC, Brier, ECE5, true multi-label V01–06,
CHAT-primary V01–06, matched subtype and >=3e8 hard-negative FPR are included.
Synthetic tests exercise the interface only and establish no challenger quality.

Run using the absolute project `PANEL_PYTHON` and `PYTHONDONTWRITEBYTECODE=1`:

```sh
"$PANEL_PYTHON" -m pytest -q tests/test_pft_act030.py
"$PANEL_PYTHON" -m ops.pft_act030_verify --artifact-root /Users/lexi/Desktop/学习/v4_app/artifacts
"$PANEL_PYTHON" -m ops.pft_act030_eval --labels APPROVED_ACT026.csv --baseline-only --act026-assessment assessment_metrics.json --output ACT030/baseline_same_exam.json
"$PANEL_PYTHON" -m ops.pft_act030_eval --labels APPROVED_ACT026.csv --predictions PROVIDED_SCORES.csv --expected-ids CALIB100_IDS.json --gate-field challenger_gate_reason --gate-policy provided_scores --output ACT030/same_exam.json
```

The local receipt contains all sixteen archive-basis/D-basis parity summaries,
separate ACT027/ACT023 anchor diagnostics, publication lineage, Reader identity,
three repair canaries and exact ACT026 regression. Numeric parity gaps, historical
PIT and challenger performance remain explicitly `CANNOT_CONFIRM` where unproved.
