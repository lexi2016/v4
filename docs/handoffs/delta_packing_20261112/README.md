# Bounded daily delta packing

The original QFQ owner wrote a 233-column Parquet footer for each changed stock, even when only one row changed. This change packs parent-owned Arrow patches in bounded batches and keeps the existing logical panel, source gates and formula kernels.

Only `ops/research_panel_delta.py` and `ops/research_panel_logical.py` change. The parent buffers at most 128 symbols or 64 MiB (smaller under the existing job budget); large/single patches retain the old layout. Each role is atomically fsynced through the original guarded `_write`. Both role hashes must verify before a batch seal commits. Small per-stock checkpoint indexes can be reconstructed from that seal without recomputation, including reviewed same-day recovery. Anchors reference a shared file once and merge only verified members into existing `symbols`/`key_rows` fields.

The reader enforces that existing advertised scope before filtered reads and stream latest-key indexing. No `symbols` or `null` means the complete physical block; `[]` means no members. Dictionary code fields are decoded only for the membership mask, retaining original field types and values. `_project`, `_columns`, row-difference math, QFQ formulas, source/PIT gates and BUY boundaries are unchanged.

Validation: 80 regression tests plus two focused original-guard tests passed. The real 5,541-stock D11 incremental row shadow preserves 23,657 changed rows per role, including historical revisions. Parquet payloads fall from 1,008.17 MB to 28.70 MB, or 40.60 MB including batch seals and checkpoint indexes. These are isolated shadow bytes, not disk reclaimed from current D11. The 11.102 GB historical bases were not rewritten.

Before/after readers separately streamed both current 17,200,149-row artifacts (233/85 columns): schema, values, NULL versus NaN, row keys and order match exactly. Evidence and source SHAs are in the JSON handoff. Old transport proof still passes its own strict validator, but does not authenticate the new logical dependency by itself; normal candidate source binding and controller readback are required.

The candidate-first test environment adds the existing active Main app as a namespace fallback solely because the frozen Git baseline omits its original `research_panel_turnover` file. The actual source is not replaced by a mock. No source data, CURRENT pointers, live apps, services, formulas, models or schedules changed.

`verify_delta_packing.py` reproduces the read-only full-reader certification and the isolated changed-row canary/full shadow; it has no collector or formula evaluation. Do not treat a shadow anchor as formal or publishable. Integration, independent review, API/UI and natural-day acceptance are not implied by Writer tests.
