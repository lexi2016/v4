# Original daily A-share QFQ repair candidate

Status: source candidate, not installed or published. Base commit:
`71d76f716f5ca8ab30c5b1b9ee7cbb4bbb428655`;
branch `codex/qfq-daily-marketwide-20261024`.

The original `ops.macos_research_panel_daily` A-share formula entry calls an
internal full-history stage. It retains the original selector/backtest output
roots and both original CURRENT files. There is no new price collector,
frontend, long-lived service or research-panel authority.

## Frozen sources and formula

`ops/vendor/data_layer_daily_formula_increment_update_v1.py` is the unmodified
current driver, SHA-256
`1b5f4caa099add5f0c369b72e0c6b9d8d80c964fe245a662290971e5142dcdae`.
`ops/vendor/build_canonical_formula_research_panel.py` is the unmodified
run-bound canonical formula, SHA-256
`074a038699eae84d093602ee6df551b5279368c5800ad78067902a496c990258`.
Only their pure functions run; neither vendor `main()` is called.
The original user formula remains unchanged, SHA-256
`924ab78f0adb0ee0705e41d7824282f40ec275a97da532ffee5b61e29d2925e6`.

The candidate reuses original BBI(3/6/12/24), double EMA10 white line,
MA14/28/57/114 yellow line, SMA/KDJ and exact B1/B2/B3. All REF(CLOSE) inputs
are preceding closes in the same QFQ-asof history. XDXR must not adjust this
pre-close again. Old Parquet supplies column templates and historical metadata;
it never supplies assumed-RAW prices. Missing original-history keys block healthy symbols. Only symbols bound to the original sync receipt as QUARANTINED and target_date_ready=false may retain their exact legacy old rows in a same-generation quarantine artifact, explicitly excluded from accepted. No unknown-basis price enters the QFQ output.

## Adjustment input contract

All price/amount/initial-volume observations come from existing TDX `.day`
files. An optional `qfq_raw_history_binding.json` binds SHA-verified existing
archive files to each symbol. A bound native hsjday.zip may supply an authoritative archive prefix, with current .day records strictly after the archive maximum. Without that explicit policy, conflicting archive/live overlap is an error. Required outputs use the original driver’s 260 preceding records as warmup; every old output key must be rebuilt or explicitly quarantined. An IPO with fewer available records retains the actual prefix count.

The original producer's `adjustment_inputs/futu_rehab/<asof>/` contains only
`get_rehab` metadata. Each symbol retains a content-addressed response, SHA,
query time, capture date, target asof, explicit empty/error/unsupported status
and bounded retry count. The maintenance invocation
`ops.collect_research_panel_adjustment_metadata` validates the original
universe receipt and its SHA, holds a single cache ownership lock, and returns
nonzero for unexpected errors. Expected BJ SDK-format rejection is a partial
metadata terminal, not all-market adjustment coverage. Cache freshness is
limited to 24 hours and the current Shanghai capture date. The original daily caller enforces at least 0.65 seconds between actual requests and retries; Stage A’s frozen source default is not used to set the daily cadence.

SH/SZ price uses chronological provider `A*P+B` before each ex-date, without
cent rounding. Volume independently uses supplied `backward_adj_factorA`.
It must not use RAW volume or reconstruct that multiplier as `1/forwardA`.
Turnover remains actual TDX turnover. SDK factor rounding and observed TDX/Futu
raw-volume differences remain provenance limits; coefficients are never fitted.
Futu documents the [price transform](https://openapi.futunn.com/futu-api-doc/quote/get-rehab.html)
and [price/volume adjustment](https://openapi.futunn.com/futu-api-doc/qa/quote.html#q16-%E5%A4%8D%E6%9D%83%E5%9B%A0%E5%AD%90%E7%9B%B8%E5%85%B3).

For unsupported symbols the internal TDX adapter can capture only the fixed
official GBBQ URL, bind the known parser SHA and retain all category rows.
Category1 has an explicit per10 affine conversion. Other categories require a
bound category-policy receipt. Unknown category4, category11/12 shrinkage or
13/14 warrant semantics are not silently discarded. The bound local BJ category policy permits category1 and explicitly named capital-snapshot categories; unresolved relevant categories block that symbol. A quarantined original symbol can retain exact legacy rows in quarantine instead of presenting invented QFQ. TDX fallback is labelled TDX convention and
does not claim Futu equality.

The normalized input is
`data/runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_adjustment_input.json`.
It requires every current/TDX symbol, complete per-symbol event coverage,
asof/revision/source SHA and raw-history references. Historical PIT is false;
this repair does not certify or modify any frozen training input.

## Rebuild and publication

Full symbol histories are rebuilt with default two configurable compute workers
(hard maximum four), SHA-bound per-symbol checkpoints and bounded batches.
Old panels are scanned once into temporary buckets; no per-symbol full-table rescan is needed. Per-role old-key conservation is checked: rebuilt accepted and exact legacy quarantine are disjoint and cover all old keys. Original target-date codes and the original sync accepted floor remain mandatory. Quarantine manifests retain prior-generation quarantine references so missing history is not forgotten on the next day.
Column names/order and date/key types remain. Paired OHLC, VOL/volume,
pre-close/pct-change, BBI, white/yellow, MA60 and J outputs use double precision
under `QFQ_V2_DOUBLE_CORE_EVENT_VOLUME`; original versions remain unchanged.

The initial publication requires both 002612.SZ and 001283.SZ current plus
recent-date displayed-0.001 lines and B1/B2/B3 oracle matches. No tolerance or
formula tuning rescues a conflict. Later days can reuse an independent
`qfq_convention_acceptance.json` only with the exact code/field-contract/user-
formula binding, matching convention and a SHA-bound initial
`PASS_FUTU_DISPLAY_ORACLE` receipt. Same-date input revisions invalidate READY.
Scheduler readiness also checks the paired generation and source/cache identity.

A nonblocking original-producer lock, fsynced journal, exact-byte pointer
backups, post-write readback and bounded rollback protect paired publication.
Interrupted PREPARED transactions roll back before the next generation starts. A controller-bound qfq_expected_current.json is required for publication; pointer bytes and old target SHA are checked at startup and before publication. Concurrent changes fail closed. After successful publication only this producer advances that expected baseline. A crash after pointer commit but before expected-baseline update stops for explicit recovery rather than adopting an unrecognized generation.
Two CURRENT files cannot be instantaneously atomic for uncooperating readers;
the candidate does not claim otherwise. Standard `meta.json`,
`task_summary.json` and explicit candidate/READY receipts remain separate.

## Activation boundary

1. Independently review the frozen metadata component/entry before actual
   metadata collection. Its exact 5800-symbol command is in the task handoff.
2. Resolve and bind original TDX archive coverage and unsupported-market factor
   semantics. Do not reuse unknown-basis Parquet prices to fill a gap.
3. Independently review core source/tests and the current raw/factor binding.
4. Under controller stage authorization, install only the reviewed internal
   modules into the existing runtime source root, with before/after SHA and
   rollback copies; keep the existing launch entry and scheduler configuration.
5. Run the original entry to create immutable candidates, verify the frozen
   two-symbol oracle, then publish/read back the original paired pointers.
6. Check the existing default reader and its numeric dtypes. Its `profile=None`
   path already follows canonical CURRENT; the old explicit two-symbol chart
   profile is not an all-market authority.

Stage A metadata acquisition is separately owned by the approved executor. No runtime install, price-panel rebuild, CURRENT publication, service/schedule
change, Git commit/push, account operation or order was performed by the source
candidate. Safety remains RESEARCH_ONLY=true, production_allowed=false,
buy_gate_updated=false and orders_sent=false. Source-only independent PASS is
not installed-entry, all-market numeric, UI or natural-slot acceptance.
