# Par native restoration diagnostics (isolated candidate)

Baseline: `b4719b0f36fcaec237f34c88aaab56a6996a0296`, branch `codex/par-native-restore-20261113`.
Writer owns only this directory and the controller-assigned implementation/native_states/validation/field_mapping artifact directories. No live V4 behavior, service, data source, trading, training or deployment changes.

The supplied Par schema contains 109 research fields. It is composed from native Python detectors, a replacement MACD/foundation projection, N/holding scores, KB8 corrections and research action descriptions. The Decimal original51 formula state is a different arithmetic implementation. It cannot seed binary64 native accumulators.

## Current products

- `build_mapping.py`: source-version-specific 109-row mapping with original function bodies, line locations and SHA256 bindings, against archived V4 selector233/backtest85 schemas. DIFFERENT requires direct source evidence. UNKNOWN preserves missing equivalence proof. It makes no EXACT claims and does not run formulas.
- `audit_original_states.py`: scoped inventory of actual supplied Par continuation objects. It does not reconstruct state from displayed outputs.
- `native_state.py`: diagnostic primitive recurrence plus typed binary codec. Python floats are written as raw IEEE754 64-bit bytes; signed zero/NaN payloads survive. Decimal is rejected. It preserves both EMA10 layers, unrounded K/D, three brick SMA accumulators, validity, dates, preclose, full raw prefix and primitive sequences. It deliberately records `all109_ready=false` and `detector_dependency_closed=false`; detector history is retained without truncation; see the separate complete109 composition candidate below.
- `native_current.py`: reuses the SHA-pinned original native detector worker, replacing only the historical primitive computation with persisted series, prefix validity with recorded flags, and the output loop with the latest row. Bounded separately seeded sliced-window calculations remain original and are counted.
- `recovery.py`: authenticates current latest109 and its15 declared dependencies, initializes original109 once, captures foundation/N internal locals directly, then reuses the exact original foundation/N step helpers and final109 composition body. Full raw rows and primitive histories remain in the new binary recovery product. Code/source/input bindings accompany the state.
- `verify_all109.py`: compares every field payload and current diagnostics, foundation/N/native outputs and primitive state against original full-prefix references on consecutive days. Synthetic mode is explicitly separate from authenticated actual Par source mode.
- `source_prefix.py`: reconstructs the original source chain through the requested physical date, using authenticated mother/tail objects, Nov2/3 daily objects, Nov4 Parquet daily bytes and Nov5/later original continuations. SHA-indexed relocation and archive handles are cached; no old Linux paths are fabricated. The841 TDX/Sina branch remains explicitly missing until its original raw adjustment source closure is available.
- `bootstrap.py`: bulk path reuses authenticated original foundation, N and Decimal51 states at the exact prefix boundary. Only the absent native hidden states scan history once; full historical109, foundation/N and51 are not recomputed.
- `batch_restore.py`: records the complete5575 scope before execution, defaults to4 processes and drains to2 on observed memory pressure. Closed Nov9 prefixes initialize independently; missing chains remain per-stock errors. Matching complete checkpoints are reused.
- `advance_restored.py`: advances existing SHA-bound new checkpoints without initialization, following actual original child-bundle references and unchanged source basis.
- `prepare_formula_prefix.py`: authenticates original mother bytes and reuses the original normalizer; the physical last date controls asof.
- `source_closure.py`: current original code/dependency identity evidence across supplied read-only roots.
- `verify_primitives.py`: deterministic original-source oracle for 3 synthetic histories, warmup boundaries, consecutive daily appends and restart serialization. Original unrounded K/D are observed through function return frame locals without altering arithmetic. Its PASS applies only to those primitives; synthetic fixtures are not authentic Par source prefixes.

## Reproduction

Use the absolute interpreter in `PANEL_PYTHON`. All scripts require explicit input/output paths. Read-only original inputs belong to the controller. Generated artifacts belong in the assigned artifact directories; do not target historical or live roots.

```sh
"$PANEL_PYTHON" -B tools/par_native_restore/build_mapping.py --par "$PAR_CODE_SUPPLEMENT" --v4 "$MAC_EXPORT_ROOT" --output "$FIELD_MAPPING_OUTPUT"
"$PANEL_PYTHON" -B tools/par_native_restore/audit_original_states.py --root "$RECOVERED_PAR_ORIGINALS" --output "$VALIDATION_OUTPUT"
"$PANEL_PYTHON" -B tools/par_native_restore/verify_primitives.py --par "$PAR_CODE_SUPPLEMENT" --output "$VALIDATION_OUTPUT"
```

The exact frozen full-task pass remains unfulfilled until actual source closure, authentic same-source history, all109 consecutive-day original-prefix comparison and complete native detector state comparison are available. Three actual Par mother-prefix canaries passed all109 and internal comparisons through20261026. Those states are separate scoped test products. Bulk initialization must close the full source chain to20261109 first, then advance only authenticated later days; it must not relabel or reinitialize the mother asNov9. All products remain research candidates, with production/trading flags false.

## Physical source index

The controller owns acquisition and inventory. The loader consumes a JSON `by_sha256` object whose values are `{"path":"/physical/file"}` (optional `original_path` for archived containers). Extracted immutable members may be indexed by their own SHA. Original archives are indexed by the SHA declared in `SOURCE_BINDINGS_V2.json`; each open archive is reused. A missing object produces a scoped `MISSING_SOURCE` record. It does not authorize a download, alternative provider or price adjustment.

## Checkpoint contract and reading

[CHECKPOINT_SCHEMA.json](CHECKPOINT_SCHEMA.json) records codec tags/endian/float bits, state paths/types, complete raw and intermediate dependencies, original input/code/runtime bindings and limitations. The absolute interpreter path is observed provenance; runtime identity uses versions/packages/platform. Original Cloud runtime is UNKNOWN. No general cross-machine bit compatibility is claimed.

Read a batch count without re-executing indicators:

```sh
"$PANEL_PYTHON" -B -c 'import json,sys; print(json.load(open(sys.argv[1]))["counts"])' "$VALIDATION_OUTPUT/bulk_nov9/BATCH_LEDGER.json"
```

Verify a receipt against its external ledger SHA and decode its latest binary:

```sh
"$PANEL_PYTHON" -B - "$RECEIPT_PATH" "$RECEIPT_SHA256" <<'PY'
import hashlib,json,pathlib,sys
sys.path.insert(0,'tools/par_native_restore')
from native_state import decode
blob=pathlib.Path(sys.argv[1]).read_bytes()
assert hashlib.sha256(blob).hexdigest()==sys.argv[2]
receipt=json.loads(blob);saved=receipt['states'][-1]
blob=pathlib.Path(saved['path']).read_bytes()
assert hashlib.sha256(blob).hexdigest()==saved['sha256']
state=decode(blob)
print(state['symbol'],state['asof'],state['count'],state['counters'])
PY
```

The batch initializer uses the exact5575 prior catalog and the current physical index. It reuses matching completed checkpoint receipts and only retries missing/changed jobs:

```sh
"$PANEL_PYTHON" -B tools/par_native_restore/batch_restore.py \
  --par "$PAR_CODE_SUPPLEMENT" --latest "$PINNED_LATEST109" \
  --dependencies "$PINNED_DEPENDENCIES_JSON" --catalog "$ORIGINAL_SOURCE_BINDINGS_JSON" \
  --index "$PHYSICAL_INPUT_INDEX" --prior-catalog "$ORIGINAL_NOV9_CATALOG5575" \
  --states "$NEW_NATIVE_STATES/bulk_nov9" --output "$VALIDATION_OUTPUT/bulk_nov9"
```

Advance existing checkpoints using `receipt-index.json` (`symbol -> {path,sha256}`) and `advance-index.json` (`symbol -> ordered original child refs`). Advance mode never initializes history:

```sh
"$PANEL_PYTHON" -B tools/par_native_restore/advance_restored.py \
  --par "$PAR_CODE_SUPPLEMENT" --latest "$PINNED_LATEST109" \
  --dependencies "$PINNED_DEPENDENCIES_JSON" --catalog "$ORIGINAL_SOURCE_BINDINGS_JSON" \
  --index "$PHYSICAL_INPUT_INDEX" --receipt-index "$BOUND_RECEIPT_INDEX" \
  --advance-index "$BOUND_ORIGINAL_CHILD_REFS" \
  --states "$NEW_NATIVE_STATES/advanced" --output "$VALIDATION_OUTPUT/advanced"
```

Only actual bound Nov10 children may extend Nov9 seeds. Nov11/12 raw observations or a factor of1 do not establish conversion to the fixed-vintage Par coordinate. Without authenticated same-source inputs/children those dates remain UNKNOWN.

Independent review initially found two resume/daily binding defects. Their FAIL evidence is preserved; the frozen4-file repair received incremental REVIEWED/PASS. Numerical/mother oracles were reused. The bulk467 accepted Nov9 initializations were retained, with no numerical reinitialization for the second pass.
