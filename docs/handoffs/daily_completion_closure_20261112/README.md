# Daily completion closure

The accepted numeric product and source generation are reused. Daily completion no longer starts the explicit historical catch-up adapter: it reads stored coverage, keeps missing history partial, and continues the existing current-day Top200/statistics/F10 chain. The original explicit bootstrap entry and its computation rules remain available.

The derivative receipt's `COMPLETE_DESCRIPTIVE_NONPIT` now explicitly has `completeness_scope=CURRENT_DAY_DERIVATIVES`. It does **not** certify complete historical labels. `history_status`, `historical_completion`, `history_bootstrap_in_daily_path` and the actual missing-date counts remain independently readable. The numeric product's historical status and rows are untouched. A complete historical view is published only through the original full proof checks when the stored coverage is truly complete.

Current consumers remain distinct: the workbench reads historical completion from the product/`history_sync`, not this task-level completion flag; the unchanged F10 entry checks the immutable successful current-day receipt's D, generation and four safety flags. Its source/universe checks, collector and failure publication are unchanged. A failed current-day Top200 source still fails the derivative step; a partial or unavailable historical module does not manufacture missing labels or set them to zero.

`SourceContext` general validation is unchanged. A continuation after moving application roots may reuse only the already signed product's original reader-equivalence proof, through the existing `semantic_reader_identity(..., proof_path=...)` validator. Every core source field, config and mathematical reader identity must match; all original proof/source/oracle/current-reader SHA and path checks run; the complete returned provenance must equal the product. Only the local continuation context is rebound. The old proof dependency must remain retained.

The original history adapter's `load` now delegates virtual projection and retained row-block transport to the existing chart owner helpers, which verify all spec/block/reconstructed hashes. Legacy physical JSON/gzip remains supported. Formula, event rules and explicit bootstrap authorization are unchanged.

The existing API source-close reader previously guessed `snapshot.parent/stage_status.json`, which stopped working after snapshots became shared immutable references. It now resolves the original admission's signed producer receipt, retains the legacy layout, and reads the accepted physical/logical selector through the existing logical reader. UNKNOWN model admissions may be skipped when finding another valid source witness; corrupt or conflicting signed evidence still fails closed. The response remains a source-date close reference with unknown exact source time, never a fabricated next-day intraday snapshot. No new persistent price store or producer is introduced.

## Validation

- 36 focused tests passed using project Python 3.14.6; use a task-owned pytest `--basetemp`.
- Real D11 read-only canary: 426 current candidates; 108 complete historical coverage; 318 incomplete, 947908 missing old label dates; zero historical bootstrap, formula or provider calls.
- Original virtual-reference failure reproduced; actual SZ/SH/BJ projections retain 51 variables/22 drawings and resolve the exact retained chain.
- Actual SZ/SH/BJ close price, daily change and amount match the already delivered daily CSV; source date/time role is preserved.
- A pure read-only Top200 build returned 200 rows using existing formal sources and frozen feature functions; no primary selection rerun or formal publication occurred.

The source checkout is partial relative to the deployed app. `ops/bootstrap_stock_event_history.py` and `infrastructure/research_workbench_quote_reference.py` were absent at baseline commit94c2 but already existed in sealed Main/API; exact before SHAs are recorded. Integration must seed from the actual matching release and replace only the bound files. The pure Top200 canary used unchanged sealed-Main dependencies plus only the two patched Main modules. Initial test-environment import failures were retained, not repaired by changing unrelated modules.

Independent review, production installation, API/UI verification, natural daily execution and real F10 collection are **not** certified by this source handoff. No services, schedules, Stage settings, source pointers, primary data, formulas, models or BUY gates were changed. Safety flags remain research-only.

## Incremental review correction

The existing quote cache now retains the original logical-reader dependency guards with its projection. Before a warm return it rechecks every block touched by the requested symbols and the canonical file identities of their deduplicated metadata references. Initial metadata SHAs are verified once per unique path; a changed or missing dependency fails closed. Unchanged warm reads do not hash large metadata again or reread table rows. Physical-cache behavior is unchanged. Six focused regressions cover warm changed/missing blocks and metadata, duplicate metadata hash counts, zero extra table reads and physical warm behavior. A real D11 three-market isolated process injected a dependency failure after warmup; the corrected warm read rejected it with one guard call and zero disk mutations.
