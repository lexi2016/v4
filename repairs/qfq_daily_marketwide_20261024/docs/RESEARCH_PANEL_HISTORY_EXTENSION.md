# Shared A-share history extension

This is an opt-in seam in the existing Mac QFQ producer. The current daily
entry and its publisher retain ownership. No live pointer, service or scheduler
is changed. The history seam and namespaced formula fields have author canaries; independent
review and full-candidate acceptance remain required. Live publication is not authorized by a canary.

## Fixed behavior

`run_daily_rebuild(..., history_extension={"path": ..., "sha256": ...})`
requires `publish=False` and isolated `data_root`, `return_root` and pointer
files below the contract's `isolation_root`. The isolated pointers may reference
the immutable accepted baseline panels. History mode skips publication journal
recovery. Calling without this argument retains daily source/clip behavior.

`raw_bindings` consumes the accepted R2 config's `stocks[].sources[]` alongside
the original current membership. Archive-only codes, including explicitly bound
BJ codes whose classification is unknown, do not depend on live `.day`
discovery. A source config is an addition, never a mask for current members.

For each exact stock/date, an archive whole row wins; native supplies the whole
row when that exact archive date is absent, for internal gaps and tails alike.
The adapter verifies original member/day hashes and retains the container/member
refs. Extracted members are byte-identical isolated copies. It does not read the
derived `raw_source_projection.parquet` as a source. Source decisions are carried
in each per-stock checkpoint as `raw_source_role`, `raw_source_ref_sha256` and
`raw_source_record_index` (zero-based original 32-byte record). The prior R2
conflict/gap receipts remain bound through the source config and evidence refs;
their source arbitration is reused.

The existing `QFQ_ASOF / QFQ_EVENT_VOLUME / RAW_TURNOVER` transform and original
driver/formula remain in charge. This is neither historical PIT certification
nor a substitution for the 194 per-signal event projector. Maximum claim is
`DIRECTION_ONLY`; raw volume-unit certification remains unknown.

## Runtime binding contract

The SHA-bound JSON has schema `qfq_shared_history_extension_v1` and requires:

- `isolation_root`, `historical_PIT: false`, `maximum_claim: DIRECTION_ONLY`;
- `baseline_generation_id`, and independent `roles.selector` / `roles.backtest`;
- each role's immutable `panel: {path, sha256}`, `key_sha256`, `schema_sha256`
  and `sidecars: [{path, sha256}]`;
- `quarantine_manifest: {path, sha256}` when the accepted role metadata contains
  one; every same-generation role artifact in that manifest must be retained;
- `source_config`, `source_policy`, `accepted_evidence[]`, `archive_refs[]` and
  `adjustment_metadata`, all exact `{path, sha256}` original refs.

`history_role_identity` defines the key digest as SHA-256 of ordered UTF-8 lines
`[stock_code,integer_trade_date]\n` with compact JSON separators. The schema
digest is canonical SHA-256 of the ordered `{name,type,nullable}` list. Baseline
file SHA additionally binds all field metadata and values. Actual extraction
of 9ffd role/footer/key/sidecar identities belongs to a separately registered
stage; these fields are not guessed from old report counts.

`prepare_snapshot` is offline in history mode. Its `adjustment_metadata` uses
the original cache `symbols` mapping, `status` and exact response refs, plus
explicit `history_coverage_start_date` and `history_coverage_end_date` for every
bound symbol. Raw provider response bodies are passed through the original
event conversion with the earlier compute start. Bound original TDX fallback
terms additionally need the same earlier history coverage. Missing coverage is
written to `qfq_input_gaps.json` and blocks the snapshot. This interface does not
grant permission to query Futu or to create a new market-data collector.

## Role conservation and missing context

History mode removes both earlier-date clips: existing symbols can gain earlier
rows and archive-only symbols can begin before a role's old global minimum.
The existing per-role old-key containment and healthy target membership gates
still apply. Added accepted rows are reported separately in role counts.

Same-generation sidecars are copied byte-identically into the isolated run,
remain excluded from accepted rows, and retain their generation, original refs
and SHA. Unknown basis sidecar rows are not promoted into QFQ accepted rows.
Foreign-market rows retain their original values under the existing contract.

Legacy auxiliary context is mapped from the same historical old row. Added
dates receive explicit null, never latest static values or numeric zero.
Observed history length is not listing age: `bars_since_list` is null for newly
admitted dates, while existing dated values are retained. The exact role schema
must mark these fields nullable, otherwise `HISTORY_CONTEXT_NOT_NULLABLE`
blocks the candidate. Missing core/formula columns remain a hard error. No
near-name column aliases or new formulas are introduced.

## Baselines, reuse, execution boundary

Local branch `codex/a-share-shared-history-extension-20261024` starts at
`71d76f716f5ca8ab30c5b1b9ee7cbb4bbb428655`. Thirteen explicitly listed original
producer dependencies are byte-identical overlays of accepted peer source;
`BASELINE_OVERLAY.json` records every SHA and receipt. This local tree is not
declared equal to accepted remote commit
`8c9dda7bddf5cf113afd002b6da73d6383a43318`, whose source is under
`repairs/qfq_daily_marketwide_20261024`.

Reuse the R2 5533-code raw-source review and current 9ffd/default-reader PASS
only within their original scope. Neither proves the new history candidate.
Do not repeat archive inventory, 22-case source profiling or unchanged 194
technical/model computation. The new test module covers archive whole-row
priority, internal gap and tail, archive-only/unknown-BJ membership, both clip
seams, nullable context, offline event gaps, no-publication guard and isolated
dual-role key/sidecar preservation.

Proposed command, **not executed by the author**:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
python -B -m pytest -q -p no:cacheprovider \
  tests/test_research_panel_history_extension.py \
  --basetemp='<E2>/canary/synthetic_pytest'
```

After official START, use one test process and one producer worker for synthetic
fixtures. A later real canary is capped at four bound symbols (301139 internal
fills, 603007 tail, one ordinary code and one already bound BJ), two workers,
BLAS one thread, no full run. Archive-only can use the synthetic fixture. Check
current load and reduce concurrency if 194 is active. Real factor/schema/role
gaps stop with exact refs and reasons; no stock filtering or fabricated fields.

The four-code real canary calls the existing per-code `raw_bindings` /
`rebuild_symbol` / `merge_rebuilt` / `_table` seams against isolated role slices
after the full baseline identity has been bound. It does not pass a four-code
snapshot to `run_daily_rebuild` with full 9ffd roles: the unchanged old-key gate
would correctly reject that narrowing. The synthetic integration test exercises
the complete producer path on its complete three-code software universe. A full
real producer build requires a separate registered/resource-approved stage.

`RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`,
`orders_sent=false`. No tests, data checks, producer, Git push, merge or deployment
are performed as part of this static author stage.


## User formula version and daily continuity

The original main-chart source is `ACTIVE_MA_USER_20261021_V1`, SHA
`924ab78f0adb0ee0705e41d7824282f40ec275a97da532ffee5b61e29d2925e6`.
`user_v1_*` fields preserve its B1/B2/B3 and chart-tag component expressions
under the pinned full-prefix numerical engine. Strict M2+ counts golden
crosses since the last DEA<=0 reset; level1 is B3 OR that strict M2+.
M2- uses the original dynamic COUNT and 21-bar uniqueness expression.
`*_daily` is the causal per-bar historical condition; `*_display_asof`
retains the source's CURRBARSCOUNT=1 today guard. Legacy primary remains
brick attack OR B3 OR double breakout, and legacy single-cross M2 fields keep
their prior meanings. The panel metadata identifies both versions explicitly.
The existing Futu chart profile supports only OHLC/BBI/white/yellow/MA60;
it does not certify the newly namespaced signal fields.

History candidates carry `history_retention_binding` in both role contracts.
The same original daily entry reads that accepted binding on later runs.
Archive rows remain first priority; frozen native rows remain intact, and
current native supplies missing/new complete records with a source receipt.
An already accepted code with no target-date bar retains its historical rows
and original per-code basis-asof. Such rows do not enter active target-member
coverage. The current original healthy-target floor still applies. The daily
schema inherits namespaced user columns and recomputes them for active codes.
This creates no additional producer, service, collector or scheduler.

`bind_full_response_history_metadata` accepts identified successful original
Futu whole responses, including `rows=[]` with explicit
`provider_full_response_zero_events/chart-asof` provenance and binds the security/status/complete row count/SHA/asof to a
full-prefix replay. This is an explicit inference from get_rehab(code)'s
unwindowed request contract, not historical publication or PIT certification.
A successful empty list uses identity adjustment only after the same security,
ret=0, row-count, SHA and capture/asof checks. Missing, failed, unsupported or
out-of-date responses do not become zero-event inputs.
Existing BJ fallback can replay a SHA-bound original official capture offline;
unknown category semantics still block the symbol.

301139's four native internal rows (20260831, 20260901, 20260902, 20260907)
remain subject to the original malformed-field gate. Source snapshots and
old role slices remain preserved; an unavailable exact-key repair is an
explicit PARTIAL gap, never permission to remove dates or zero-fill labels.


Cached official TDX replay cannot cover a target after its bound capture-date
ceiling. The original online daily caller may refresh a stale capture through
the existing official path; the refreshed response and an immutable dated
capture receipt enter source identity. Offline replay never refreshes.
Optional archive/evidence reference arrays default to empty when no archive or
extra evidence is used; malformed reference-list types fail before execution.
