# Current 247 candidates: delta canary handoff

The three-sample independent PASS source/tests/handoff were committed first as
`75d611995` using eight explicit paths; no push or unrelated dirty inclusion.
The original four tests and three actual charts were not rerun.

This delta changes only the same helper/test and this new handoff directory:

- The allowlist is exactly the unique 247 symbols shared by current product
  rows and frozen coverage. CLI symbols must be explicit and inside it; no
  all-market/default-all path exists.
- Both the legacy shared `samples` cache and the 244 per-stock `sample` cache
  are supported. Cache SHA, bar SHA/count/date/basis/generation, source refs,
  product manifest/artifact/row refs and original engine/formula pins remain
  bound. An individual mismatch stays CANNOT_CONFIRM.
- The old three require their independent receipt/manifest and are referenced
  without computation or copying. Their projection/HTML SHA remained identical.
- New projections use deterministic lossless `.json.gz`. HTML embeds gzip/base64
  payload decoded by the browser's built-in `DecompressionStream`; there is no
  large duplicate uncompressed full-prefix file. This is a format/transport
  delta; original R19 `choose`/`paint`, colors and drawing semantics are unchanged.
- Each new output has a binding-specific checkpoint; a matching completed one
  reuses its exact files. `export_one` is the independent job primitive for the
  later bounded controller. The CLI remains explicit and sequential; it does
  not itself schedule a resource-monitored worker pool.

Only new canary **600814.SH** ran: 7781 full-prefix rows, each 51 values/22
drawings, unsupported types 0; 1.9868 seconds; peak RSS 429,948,928 bytes. Its
27,954,497-byte uncompressed JSON was not stored. Projection gzip is 2,468,984
bytes and compressed-payload HTML 3,288,380 bytes. Both decoded rows exactly
match the projection. Real local Chrome readback and opened PNG show D29,
7781 rows, DOM 51/22, 240 triggered drawings in the original last120 view,
nonempty canvas and no errors. Browser closed; its private profile was deleted.

Three delta-only targeted tests passed. They cover the 247 allowlist and scope
rejection; legacy/new cache shape with negative refs/bar SHA; lossless gzip and
embedded payload, unchanged renderer functions, and completed checkpoint reuse
without a second engine call. Exact source SHA/commands and actual readback are
in `DELTA_REVIEW_CAPSULE.json`; source-only diff is `INCREMENTAL.diff`.

The metadata row sum for the 244 new symbols is 714130. Linear scaling from this
single canary estimates 182.35 seconds serialized / 13.0 seconds ideal at14
workers, excluding scheduling/I/O/browser costs; approximately226.6MB gzip plus
301.8MB HTML. These are estimates, not SLA or upper bounds. Current machine:
18 cores/128GiB, memory-pressure free93%, disk free352GiB. Fourteen times canary
peak RSS is about6.02GB. Root's later controller must still enforce64GiB job /
24GiB reserve, monitor real pressure/RSS, stop new submissions and drain/checkpoint
when needed. No batch pool has been started by this delta.

There are243 missing outputs after the successful new canary and unchanged old
three. Root's requested research-review queue priority is002003.SZ,601088.SH,
603444.SH, followed by the remaining frozen candidates. `PLANNED_ORDER.json`
records this only as queue order, not new membership, ranking or stock PASS.

The delta subsequently received independent PASS and Root's explicit execution
gate, both preserved in this folder. The remaining243 export and actual PNGs
are now complete: see `BATCH_COMPLETION.md` and `COMPLETION_SUMMARY.json` for the
247-symbol mechanical PASS. No native-panel certification, new producer,
source/price/calendar/formula/pool/service change, historical labels/returns
bootstrap, installation, deployment or push occurred. Existing native-TDX/PIT
and dense-label limits remain. Mechanical chart output is not stock approval.
