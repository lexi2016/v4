# V4_FORMULA_MARGIN_SHADOW_V1

This is a read only, forward shadow experiment for the real V4 Hong Kong
Connect stage order. It records a production B arm and a formula F arm at the
same cutoff. `selection.py` contains only a default-off, side-effect-only
capture hook: with the hook omitted, the selector envelope and ordering are
unchanged; a callback or disk failure is swallowed and cannot change the
production result. The hook does not alter a BUY gate, an order path, a
service, a scheduler, or a production artifact.

The implementation is in
[`stage_center/formula_margin_shadow.py`](../stage_center/formula_margin_shadow.py)
and the only manual entry point is
[`ops/run_formula_margin_shadow.py`](../ops/run_formula_margin_shadow.py).

Every input states one admission mode. `ENGINEERING_FIXTURE` is available for
deterministic arithmetic, immutability, and selector-hook tests; its labels
and evaluations are `ENGINEERING_ONLY`, with `hit_ready=false`,
`counts_as_forward_day=false`, and `natural_sample_count=0`. It never enters a
natural-day denominator. `REAL_AUTHORITY` is the intended forward mode, but
this checkout keeps it fail-closed until the existing owner supplies the
exact-date membership manifest/receipt chain and the same-membership-bound
final-close contract. A caller supplied truth list, coverage value, source
string, tie-break, or timestamp cannot upgrade either mode. Engineering
selector captures use `FORWARD_SHADOW`; `FORWARD_NATURAL` is reserved for a
runtime-authorized capture.

The three frozen natural stages and their exact Shanghai cutoffs are:

| stage | cutoff |
| --- | --- |
| `STAGE_0930_0935` | `09:35:05` |
| `STAGE_0945_1030` | `10:30:00` |
| `STAGE_1445_1500` | `15:00:00` |

The input is an already materialized real V4 snapshot. The runner does not
fetch or calculate anything. A real run must contain exactly the D1 Top100
members, each with an explicit `eligible` flag and a contiguous original
`production_rank` for eligible rows. The persistent CLI requires this with
its default mode. Short-pool canaries are available only through the
in-memory test function and never through the manual freeze or capture
commands.

If the currently available V4 surface stores only a production Top10, it is
insufficient input: this tool cannot manufacture the missing candidate rows or
claim a complete D1 pool. Export the real cutoff snapshot through the existing
V4 stage-selection readback/manual snapshot interface, add the already
verified H/N/U state rows and their source hashes, then run `preflight` and
`freeze` on that local JSON. There is no Top10-only fallback and no historical
recovery route in this experiment.

For an explicit local readback, the existing verified selection call is:

```python
from stage_center.selection import SelectionStore

top10 = SelectionStore(selection_root).read_verified(
    trade_date, stage_id, "HK_CONNECT"
)
```

That call is useful to compare the recorded B arm, but it returns the
production recommendation surface and cannot by itself produce this experiment
because it does not prove the full D1 Top100, all comparator rows, or the four
formula states. The operator must pass a separate local JSON snapshot to this
tool with `rows` containing those fields. If that full readback is unavailable,
the only correct result is `CANNOT_CONFIRM` and no candidate artifact is
created.

The supported capture entry point consumes the same raw rows that the real
selector call receives. It invokes `select_hk_four_lane` with the opt-in hook,
records the complete pre-cap sorted output, and assigns ranks from that
output. The caller does not provide `production_rank`, `production_top10`, or
a second comparator. A capture input must provide these top-level fields:

```json
{
  "metadata": {
    "admission_mode": "ENGINEERING_FIXTURE",
    "observation_mode": "FORWARD_SHADOW",
    "trade_date": "YYYYMMDD",
    "stage": "STAGE_0930_0935",
    "cutoff_ts": "YYYY-MM-DDT09:35:05+08:00",
    "captured_at": "YYYY-MM-DDT09:35:00+08:00",
    "input_sha256": "...64 hex...",
    "rule_sha256": "...64 hex...",
    "raw_artifact_sha256": "...64 hex...",
    "source_artifact": {"path": "/abs/source.json", "sha256": "...64 hex..."},
    "rule_artifact": {"path": "/abs/rule.json", "sha256": "...64 hex..."},
    "formula_provenance": {"input_sha256": "...", "rule_sha256": "...", "source_asof": "...", "frozen_at": "..."}
  },
  "rows": ["the exact raw selector input rows"],
  "formula_manifest": {"version": "...", "input_sha256": "...", "rule_sha256": "...", "artifact": {"path": "/abs/formula.json", "sha256": "..."}, "rule_artifact": {"path": "/abs/formula-rule.json", "sha256": "..."}, "states": ["per-code f1..f4 H/N/U"]},
  "d1_manifest": {"version": "...", "sha256": "...", "artifact": {"path": "/abs/d1.json", "sha256": "..."}},
  "time_evidence": {"source": "selector capture", "captured_at": "..."}
}
```

The source, rule, D1, and formula artifacts are read and hash-checked. Their
actual member/state rows must match the selector input and the formula
manifest. If any evidence is absent or late, the selector result may still be
returned for production observability, but the shadow writes an immutable
`invalid_ledger.json` and does not publish a qualified candidate. The manual
capture command is:

```bash
.venv/bin/python ops/run_formula_margin_shadow.py capture \
  --input /abs/selector_capture_input.json \
  --output-root /abs/shadow_root
```

This is an operator-invoked readback. No scheduler, service, or automatic
production integration calls it in this version.

The capture receipt uses schema
`v4.formula_margin_shadow.capture_time_receipt.v2`. It is created only after
the selector returns its envelope. `production_run_id`, `production_artifact_id`,
`production_algorithm_sha256`, `raw_artifact_sha256`, `selection_status`, and
the Top10 come from that returned envelope. A caller supplied `run_id` or
`artifact_id` is advisory; if it is present and differs from the returned
identity, the capture is rejected. The callback Top10, returned Top10, and
shadow B arm must be identical. `shadow_invocation_id` is a separate runtime
capture event id and is never substituted for the deterministic production run
id.

`freeze_snapshot()` is a direct engineering freeze. It records
`capture_origin=DIRECT_ENGINEERING_FREEZE`, `invocation_verified=false`,
`invocation_status=NOT_VERIFIED_ENGINEERING_FREEZE`,
`counts_as_forward_day=false`, and `natural_sample_count=0`. A hand-written
receipt claiming `selector_invocation_status=COMPLETED` or
`invocation_verified=true` is rejected by this path. Only the internal path
that has observed the selector return may create an invocation-verified
receipt.

For an invocation-verified capture, the exact consumed source bytes are copied
under the run root without symlinks:

```text
provenance/production_source.bin
provenance/production_rule.bin
provenance/d1_manifest.bin
provenance/formula_state.bin
provenance/formula_rule.bin
selector_result.json
```

Their SHA-256 values are recorded in `selection_receipt.json`, together with
the independent `source_artifact_sha256` field. `verify` reports
`frozen_integrity_status=PASS` with
`integrity_scope=LOCAL_FROZEN_AND_SEALED_PROVENANCE` only after it checks the
sealed copies, selector result hash, identity bindings, and baseline parity.
This is a local frozen-integrity result; it does not re-read external source
paths. The optional external audit is explicit:

```bash
.venv/bin/python ops/run_formula_margin_shadow.py verify \
  --run-root /abs/shadow_root/YYYYMMDD/STAGE_0930_0935 \
  --external-revalidate
```

It reports `external_source_revalidation=NOT_REQUESTED`, `PASS`, `DRIFTED`,
or `MISSING`. External drift or deletion does not invalidate a locally sealed
run.

## Frozen selection rule

The baseline is the first ten rows in the supplied production order. The
order is checked against the V4 comparator
`hk_legacy_stage_sort_key` in descending order:

```text
(bucket_weight, no_trade_gate, stage_score, pct_chg, volume_ratio)
```

`stage_score` is the real production score. A display-only `score` is rejected
when `stage_score`/`production_score` is absent. Missing eligibility, rank,
comparator version, score, or comparator inputs fails closed; a momentum/CF
order is never substituted. `formal_eligible=false` is retained as a safety
marker and does not change the explicit `eligible` field.

The equivalent class contains the full score-before key and the exact
multi-label lane:

```text
(canonical_lane_labels, bucket_weight, no_trade_gate)
```

Lane labels are compared as a canonical set. A string remains one literal
label; the tool never splits strings or maps a bucket/status to a lane.

For rank 6 through rank 15, adjacent pairs are used only when both rows are in
rank 10's equivalent class. Their finite non-negative
`stage_score[r] - stage_score[r+1]` gaps are collected and their median is the
frozen `tau`. If there is no such pair, a stage is invalid. An increasing score
inside the class is invalid. `tau=0` is allowed and means that only exact
score ties can be reordered.

The ambiguous set is the same equivalent class with
`abs(stage_score - stage_score_10) <= tau`. Only this set is stably reordered:
any of `f1_state` through `f4_state` equal to `H` comes first, and all other
rows (`N` and `U`) retain their original relative order. Multiple H states do
not add weight. No formula state crosses a lane or a comparator class, and no
weight is trained.

Every supplied member is recorded in `members.json`, including the original
rank, lane, score, formula states, stage price semantics, both arm flags and a
selection reason. The two ten member files are:

```text
baseline_top10.json    # B: exact original production Top10
candidate_top10.json   # F: frozen margin/tie-break Top10
selection_receipt.json # hashes, source binding, cutoff, rule and tau
```

All four files are published with create-only hard-link publication. Existing
files are never replaced. The receipt binds the three artifact SHA-256 values
and has a separate payload hash; `verify` detects tampering before labels or
metrics are read.

## PIT and source binding

The snapshot metadata must provide:

```json
{
  "observation_mode": "FORWARD_NATURAL",
  "trade_date": "YYYYMMDD",
  "stage": "STAGE_0930_0935",
  "cutoff_ts": "YYYY-MM-DDT09:35:05+08:00",
  "source_version": "real-v4-production-version",
  "input_sha256": "...64 hex...",
  "rule_sha256": "...64 hex...",
  "comparator_version": "hk_legacy_stage_sort_key",
  "run_id": "real-production-run-id",
  "formula_provenance": {
    "source_version": "verified-formula-state-version",
    "input_sha256": "...64 hex...",
    "rule_sha256": "...64 hex...",
    "source_asof": "D or earlier, or an explicit pre-cutoff timestamp",
    "frozen_at": "pre-cutoff timestamp"
  }
}
```

Formula values are consumed as already verified H/N/U states. The shadow never
runs a formula producer. If an artifact path is supplied under
`formula_provenance.artifact`, its bytes and SHA are checked. Formula
`source_asof` and `frozen_at` may not be after the stage cutoff or on a future
trade date. Stage prices must be positive and carry a pre-cutoff timestamp,
currency, adjustment mode and source.

## Close labels and truth scope

Labels are accepted only after all selection artifacts are frozen and are
written below a separate `labels/` directory. The current user lock fixes the
truth to:

```text
HK_CONNECT_FULL_UNIVERSE_CLOSE_GAIN_TOP20
```

The close input must prove the full valid HK Connect member universe and its
complete same-day close-gain source from actual source bytes. It must provide
a member-version, source-version, input SHA, manifest SHA, universe count,
coverage ratio 1.0, a deterministic same-gain tie-break, and a gain
definition. The tool computes the Top20 from those full rows; a self-reported
`truth_top20_codes` list is only checked against the computed result and is
never trusted as the source. Missing or late member/gain coverage is recorded
in `invalid_ledger.json` and makes the hit unit `CANNOT_CONFIRM`; missing
gains are never treated as zero or a loss. D1 members outside the calculated
Top20 are expected and do not produce `LABEL_NOT_IN_D1_POOL`.

After hit truth is independently valid, missing close price, currency,
adjustment mode, or close-price-source on a selected name affects only the
stage-to-close markout. The label unit remains usable for hit counts and
recall, while markout is reported as `CANNOT_CONFIRM`.

The close label rows contain:

```text
close_top20_rank
hit_top20
close_price
close_price_source
currency
adjustment_mode
```

The label payload binds the frozen selection receipt SHA. A conditional
positive-market-cap Top20, a D1-only Top20, a full-HK-without-membership
snapshot, an old archive, or a legacy fixture cannot satisfy this scope.
The source identity, exact-date membership schema, final-close/gain field,
tie-break, and suspension policy must come from the existing V4 authority
contract. Caller-provided counts, source-version strings, tie-break labels, or
combined JSON do not establish that authority. Until that contract is bound,
`REAL_AUTHORITY` labels are rejected with an immutable invalid ledger and
remain `CANNOT_CONFIRM`; no caller-supplied contract can upgrade them. The
repository fixtures that exercise the arithmetic are explicitly
`ENGINEERING_ONLY` and do not provide this authority contract. A Top20
boundary tie is rejected when the source does not provide an authoritative
tie-break. Suspended members are not deleted or imputed as zero; absent
authoritative close/gain evidence invalidates the truth unit.

The current owner evidence is still incomplete: the formal exact-date member
manifest/receipt chain, a same-membership-bound final EOD close contract, an
accepted adjustment/corporate-action definition, a source tie-break contract,
and a suspension policy have not been delivered. A panel fallback or a
collection-time payload cannot fill those gaps.

## Metrics

`evaluate` reports planned, valid, engineering-only, and invalid stage units.
Engineering-only units retain diagnostic hit and markout separation but are
excluded from all natural denominators; their diagnostic changed-in/out counts
are reported separately. For `N` valid units,
P@10 uses exactly `10N` as its denominator. Recall@20 uses `20N` and is only
reported for complete truth units. It also reports the number of truth Top20
members present in the D1 pool (`d1_pool_recall_at20`), which is the selection
ceiling caused by pool omission; it is kept separate from B/F hit counts.

The aggregate includes B/F hit counts, net delta, changed-in and changed-out
counts, per-stage totals, and per-trade-date totals. No stage is selected as a
winner. The +5 percentage point capacity check uses only the number of
changed-in seats as possible positive corrections:

```text
required_capacity = ceil(0.05 * 10 * planned_units)
```

If changed-in seats are below this number, the result is
`INSUFFICIENT_INTERVENTION_CAPACITY_FOR_5PP` before labels are needed.

Stage-to-close markout is auxiliary. It is populated only when stage/close
prices have matching currency and adjustment semantics. It reports average,
median, positive ratio and worst value for B, F, entered and exited names;
semantic or price gaps remain `CANNOT_CONFIRM`.

## Manual commands

From the V4 project root:

```bash
# Engineering preflight; this never creates a run and never counts a day.
.venv/bin/python ops/run_formula_margin_shadow.py preflight --input /abs/input.json

# Raw selector-input preflight; this only authorizes invoking the selector.
.venv/bin/python ops/run_formula_margin_shadow.py preflight-capture \
  --input /abs/selector_capture_input.json

# Real run: exact D1 Top100 is required by default.
.venv/bin/python ops/run_formula_margin_shadow.py freeze \
  --input /abs/real_v4_snapshot.json \
  --output-root /abs/shadow_root

# Append the close truth only after freeze has succeeded.
.venv/bin/python ops/run_formula_margin_shadow.py label \
  --run-root /abs/shadow_root/YYYYMMDD/STAGE_0930_0935 \
  --input /abs/full_hk_connect_close_truth.json

# Verify immutable B/F artifacts and evaluate one or more units.
.venv/bin/python ops/run_formula_margin_shadow.py verify \
  --run-root /abs/shadow_root/YYYYMMDD/STAGE_0930_0935
.venv/bin/python ops/run_formula_margin_shadow.py evaluate \
  --run-root /abs/shadow_root/YYYYMMDD/STAGE_0930_0935
```

`preflight-capture` validates exactly 100 unique raw D1 rows, the actual
production source/rule bytes, the D1 manifest, the 100-code H/N/U formula
state and rule artifacts, and bound time evidence. A successful response is
`READY_FOR_CAPTURE_INVOCATION`; it is neither `FROZEN` nor a natural sample.
The static preflight cannot prove a natural timestamp. During a real capture,
the private runtime clock is checked in Asia/Shanghai against the exact stage
window and the caller's `captured_at` and `time_evidence.source` are ignored
as proof. The capture writes an immutable `capture_time_receipt.json` bound
to the production run id, raw/source/rule SHA, D1 manifest, formula state and
rule artifact SHA, shadow rule, comparator, and the real
`stage_center.selection.select_hk_four_lane` invocation. Receipt and selector
parity failures are invalid ledger entries; the production selector result is
left unchanged.
Dynamic production rank, baseline parity, equivalent-class checks and `tau`
are evaluated only when `capture` invokes the real selector hook. Static
preflight and capture share the same admission helper, so an input cannot
pass preflight through a weaker schema than the capture path.

The existing archive rejection canary is an engineering check only. It does
not start the five-day canary, the fixed twenty-day pilot, or the independent
forty-day validation. No automatic task is created. On 2026-09-19 there is no
natural Hong Kong trading sample in this implementation; the experiment must
remain `CANNOT_CONFIRM`/planned until real cutoff snapshots and the frozen full
universe truth arrive.

All artifacts carry:

```text
RESEARCH_ONLY
shadow_only=true
production_allowed=false
buy_gate_updated=false
orders_sent=false
automation_created=false
```
