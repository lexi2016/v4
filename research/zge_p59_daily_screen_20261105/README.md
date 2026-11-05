# Phase59 D05 fixed-model research inference

This consumer loads the existing final T5 model through the pinned restricted
`zge_phase59_mac_continue_20261105/runtime.py`. It produces no features, labels,
training, weights, API/UI updates or trading instructions. The model remains
`DIRECTION_ONLY`; scores are uncalibrated and are not probabilities or expected
returns. T1/T2 are outside this execution.

Baseline: `92bf34b47e0c1238221df6d919e918e2562a24f8`.
Model SHA: `ba3553516af05dec467299579dccc7d8c418882dbd4cc89433b4722c2df9dd43`.
Feature-order file SHA: `6d4e8f60a7854f1895976e1d462975d4645fc0dc01d2b92661d8111b28172325`.
Date: `20261105`; A-share generation:
`63986092da44625a69d34f5f98a300c8ba685ea023dbaa007639207caa3ea109`.

Source and output scope are frozen in
`/Users/lexi/Desktop/学习/agents调试/v4_model_daily_screen_20261105/TASK_CAPSULE.json`.
The feature owner is `phase59_post1015_oos_20261105`; wait for its accepted
projection and source/semantic receipt. Never manufacture a replacement input.

## Controller binding

Before real inference, Root confirms a binding JSON and its SHA. This is an
explicit identity binding to the owner's accepted files, not a new certification
or a second feature producer. If the existing owner has different column names,
agree a mechanical mapping; do not infer formulas from similar names. Optional
`feature_column_map` and `coverage_column_map` objects map canonical names to
original names, with entries in desired output order. The original files and
their hashes remain unchanged. Optional `domain_value_map` binds each exact
original string to boolean/null; unmatched values are rejected. These maps
perform only projection/renaming, never numerical feature derivation.

Required JSON keys:

```json
{
  "signal_date": 20261105,
  "source_generation": "63986092da44625a69d34f5f98a300c8ba685ea023dbaa007639207caa3ea109",
  "model_sha256": "ba3553516af05dec467299579dccc7d8c418882dbd4cc89433b4722c2df9dd43",
  "feature_order_sha256": "6d4e8f60a7854f1895976e1d462975d4645fc0dc01d2b92661d8111b28172325",
  "top_n": 10,
  "tie_break": "ts_code ascending",
  "controller_accepted": true,
  "upstream_execution_id": "OWNER_EXECUTION_ID",
  "domain_definition": "Original owner rule identity and SHA, unchanged",
  "features": {"path": "/absolute/owner/features.parquet", "sha256": "OWNER_SHA"},
  "coverage": {"path": "/absolute/owner/coverage.parquet", "sha256": "OWNER_SHA"},
  "upstream_acceptance": {"path": "/absolute/owner/accepted_receipt.json", "sha256": "ACCEPTED_SHA"},
  "feature_binding": {"EACH_OF_THE_87_REAL_FEATURE_NAMES": "SOURCE_BOUND_OR_TRAINING_FROZEN_UNKNOWN"},
  "flags": {"RESEARCH_ONLY": true, "production_allowed": false, "buy_gate_updated": false, "orders_sent": false}
}
```

Features contain `ts_code`, `signal_date`, all original 87 feature columns in
the pinned order, `target_domain` (actual boolean or null), and `domain_reason`.
The existing P54 11, behavioral 6 and P53 7 columns must remain null and have
`TRAINING_FROZEN_UNKNOWN` bindings. Remaining fields have `SOURCE_BOUND` bindings.
For a `BOUND` row all remaining values must be finite; there is no fill operation
in this consumer. Frozen original preprocessing and structural missing-value
handling remain inside the original model interface, including masked z11.

Coverage contains exactly the accepted 5808 unique A-share codes for D05,
`input_status` (`BOUND`, `UNAVAILABLE`, or `NO_D05_BAR`) and `gap_reason`.
Every unavailable row needs an explicit reason. Every bound code needs one
complete feature row. Codes lacking a D05 bar remain in the export with null
scores. The owner supplies this coverage; Top200 and four-group candidates
cannot replace it.

## Ranking and outputs

Run original `model.predict` once on all bound rows. Export all 5808 coverage
rows with scores where available and per-code status. `score_rank` orders all
scored rows by score descending then code ascending. `observation_rank` ranks
only `target_domain == True`; at most the first 10 form the main observation
list. False/unknown domains cannot enter it. A small domain is never padded.
The exported domain status/reason is upstream evidence, not a new rule.
Each row also carries the original projection path/SHA, its zero-based input row
position after any explicitly bound projection, observed unmasked count, exact
missing-feature names and frozen-UNKNOWN count. Missing projection rows retain
null row identities and the owner's coverage reason.

Each unique execution directory contains the frozen execution contract,
`ALL_CODES_RANKED.parquet`, its CSV, `PRIMARY_OBSERVATIONS.csv`, registry
start/terminal receipts and `RUN_RECEIPT.json` (or retained `FAILURE.json`).
Parquet is read back exactly; CSV code/rank/score identity is checked without
another model call. D+1 and T5 outcomes remain null. Root can separately compute
the Top200 intersection after selection is frozen.

Registry writes use the existing official adapter and lock, preserving all
concurrent appended events. Only the original four exact historical SHA
exceptions apply; the shared validator and old ledger bytes are unchanged.
Global preexisting semantic debt is retained in the receipt. No registry event
is written for synthetic unit tests or the initial read-only diagnosis.

## Commands

Use the already verified training environment; install no dependencies:

```sh
cd /Users/lexi/.codex/worktrees/zge-p59-daily-screen-20261105/v4_app/research/zge_p59_daily_screen_20261105
/Users/lexi/Documents/Codex/2026-08-13/factor-mining-mac/.venv-training-v1/bin/python -B -m unittest -v test_daily_screen
# Only after Root confirms upstream binding:
/Users/lexi/Documents/Codex/2026-08-13/factor-mining-mac/.venv-training-v1/bin/python -B screen.py --binding /absolute/accepted_binding.json --binding-sha256 CONTROLLER_CONFIRMED_SHA --execution-id ZGE_P59_D05_UNIQUE_ID
```

Synthetic tests cover SH/SZ/BJ, masks, missing values, date/order/key failures,
strict domain types, no-padding Top10, ties and output readback. They do not
certify real source semantics. Reuse the owner's accepted evidence and examine
only three representative market inputs before the one real inference.

At all times: `RESEARCH_ONLY=true`, `production_allowed=false`,
`buy_gate_updated=false`, `orders_sent=false`. No deployment, service operation,
production pointer write, model performance acceptance or natural-run claim.

## Current result, 2026-11-05

`PREPARED` and `TESTED` (14 synthetic consumer tests passed); fixed-model input
is `BLOCKED_FIXED_MODEL_INPUT_COMPATIBILITY`. The owner's published feature map
identifies 19 missing producer definitions: seven P53 fields already covered by
the frozen mask and 12 additional JCB/tactic/reversal fields. Further C-event
inputs remain UNKNOWN, and several mappings are explicitly proxies. This does
not satisfy this consumer's unchanged 63 `SOURCE_BOUND` inputs.

The fixed `ba355…dd43` model has not been loaded for this task. No real inference,
real registry execution, scores or observation list has been produced. There is
no additional mask, replacement weight or approximate feature producer here.
The original owner continues its separately versioned mapped-feature work;
its output must retain that distinct identity. Root coordinates reuse. See
`RESULT.json` for the exact source-evidence hashes and missing nonmasked fields.
