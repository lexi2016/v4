# ACT-071A V1.1 D-only protocol

A signs each case with `ACT070A_CASE_INPUT_V1_1` and accepts only `ACT070A_B_OUTPUT_V1_1` in B responses. The four inherited cases retain their original D, symbol, OHLCV, provenance and B2 eligibility. Their scope is `EXPOSED_REGRESSION` and they are stored in `01_CALIBRATION_4D_V1_1`. The migration consumes four pinned case inputs, their D-only SVGs and their separately pinned A receipt. The V1 files and source evidence remain byte-identical.

## Run on A

Use the existing V4 `PANEL_PYTHON` from the V1.1 worktree root. The validators import unchanged V1 protocol helpers from `research/act070a/`. The calibration builder also reads the frozen V1 Schema and KB cards in that source directory. A renders the PNG from the exact same SVG in the same dimensions using the Mac `/usr/bin/sips` `sips-316` renderer. A verifies the SVG against the ordered 35-session map and regenerates the PNG to test byte parity. Each file digest is bound by the trusted case digest.

```sh
"$PANEL_PYTHON" -B -m research.act071a.selftest
"$PANEL_PYTHON" -B -m research.act071a.build_cases \
  --v1-root CONTROLLED_V1_CASES --out NEW_CASE_ROOT
"$PANEL_PYTHON" -B -m research.act071a.validate_b_output \
  --case-dir NEW_CASE_ROOT/01_CALIBRATION_4D_V1_1/C01 \
  --trusted-receipt NEW_CASE_ROOT/A_CASE_RECEIPT_V1_1.json \
  --output RAW_B_RESPONSE.json
```

A keeps its receipt outside every B case directory. Each case contains only `chart.svg`, `chart.png`, `input.json`, `act071a_b_output_schema_v1_1.json` and `kb_rule_cards_v1_1.json`. A uses the separately held receipt to verify the case ID and `input_sha256`, then checks the raw B JSON for duplicate keys and validates its five top-level and eleven per-claim fields.

## Claims

- `PHASE` claims require one of `UP_LEG`, `DOWN_LEG`, `RANGE`, `MIXED` and `UNRESOLVED`. All other claims must carry `"phase_label": null`.
- Each anchor link has `relation` and `ref`. Use `REFERENCE` for ordinary chart references. `INVALIDATES` requires `OLD_ANCHOR_INVALIDATION`, a registered prior support object and a separately cited, observed active-anchor close break for that same A-bound identity.
- Prior OHLCV aggregate evidence is exposed in derived rows as `ohlcv`. Price references require `open`, `high`, `low` or `close` from a mapped chart bar. Span references require its `date`. The aggregate may be used as evidence or counterevidence when it is observed.
- A reports the event date only when the frozen time rule resolves it. `first_knowable_date` is the latest knowable date across all refs, including counterevidence, for the complete assessment. Uncomputable rules retain `UNRESOLVED`.
- The whitelist is D-only. A preserves the candle-based B2 necessary-condition result and the unknown B2 chain. A rejects claims using missing-source facts or promoting candidates into formal results.

The synthetic selftest uses zero models and zero market data reads. It checks the 21 inherited attacks, all five V1.1 attack classes, legal claims and both chart bindings.

`RESEARCH_ONLY=true`, `S_FIT=0`, `B_FIT=0`, `PRODUCTION_ALLOWED=false`, `buy_gate_updated=false`, `orders_sent=false`.
