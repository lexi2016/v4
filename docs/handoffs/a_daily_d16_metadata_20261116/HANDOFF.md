# D16 ordinary snapshot admission metadata

The archived producer at `19d0576a6` (2026-10-28) already had two different metadata paths. The history-extension path emitted `history_end_date` and accepted references. The ordinary path computed the sorted native dates and omitted the observed end date and admission references. The later `1de444561` repaired a single symbol with its own evidence. The frozen admission helper still requires both a matching end date and verified references.

The patch targets the exact R2 Main copy of `ops/research_panel_adjustment_inputs.py`. The ordinary raw scan reports its observed end date separately, so retained-history and quarantine selection still see the original binding fields. Only after a current research cache factor branch has validated the symbol does the producer attempt admission metadata binding. It checks the immutable prequery sync could be tied to the exact current authority output, the dated official ZIP and symbol member, acceptance and native path/SHA, and applicable per-symbol factor evidence. BJ official terms must cover the entire observed prefix and include per-symbol rows. Failure to establish that chain leaves the two fields absent. The consumer admission rule and factor behavior retain their existing semantics.

Isolated verification exercised the original and candidate `prepare_snapshot` on all 35 D16 cases. It reused the exact cached factor metadata, checked its decisions with the real original plan, verified native bytes, and used the exact official ZIP. The original helper returned the history-end UNKNOWN for all 35 inputs with the original producer. With the candidate inputs it admitted 14 research-cache carry and 21 BJ official-terms symbols. The original events, raw references and quarantine decisions matched. The isolated verification did not calculate formula groups or publish a new D16 generation. The formal D16 snapshot and index remain the published ones.

The one-file patch applies to the before SHA in `OVERLAY_INVENTORY.json` and changes the QFQ input-adapter SHA. An installation requires the existing reviewed successor-tuple procedure. This patch contains no tuple acceptance or change to the source generation guard. Restore the original immutable R2 file to reverse the source change.

Focused checks restore the exact patch and exercise raw-date capture plus stale, malformed, unbound and no-factor-proof cases.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  "$PANEL_PYTHON" -m pytest -q -p no:cacheprovider \
  tests/test_a_daily_d16_admission_metadata.py --basetemp /path/to/isolated-pytest
```
