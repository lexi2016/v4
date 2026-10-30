# Saved observation and execution binding

This is a narrow projection of existing V4 owner artifacts. It adds no Futu
A-share path, account API, alternative market base or history bootstrap.

Current data boundaries supplied by Root: 247 official D30 daily archive rows
are available from the existing official package; their exact source clock is
unknown. D30 package arrival does not bypass the authoritative panel's
`SOP_REBIND_REQUIRED:000016.SZ` failure. The old failed/WAIT receipts remain.
Japanese new close evidence is a dated official-site web observation; automatic
HTTP403 remains a gap. Korean stored raw index samples use the latest aligned
previous daily close, never the five-day `chartPreviousClose` baseline.

Intraday status is `CANNOT_CONFIRM_INTRADAY_SOURCE`: the original minute lane
has no yesterday-close/cumulative-amount substitute, and native quote
`servertime` cannot establish a trading date. The known connector failure is
not rescanned across80 hosts on each timer. A saved timer invocation or
archived daily value does not establish a natural ten-minute quote chain.

## Private host binding

Retain schema `V4_MAC_WORKBENCH_BINDING_V1`, the four safety flags and existing
explicit date/plan refs. Add `statistics_root`, `observation_root`, optional
`execution_root`, and a hash-bound `calendar` ref. A direct
`workflow_execution` ref plus `workflow_date` is also supported.

```json
{
  "workflow_receipt_sources": {
    "15": {"kind":"A_DAILY_PANEL_RECEIPT","root":"<original A receipt root>"},
    "17": {"kind":"A_DAILY_PANEL_RECEIPT","root":"<original A receipt root>","retry_only":true}
  }
}
```

Roots are absolute canonical local directories. The narrow adapter reads
`a-YYYYMMDD.json`, checks schema/lane/date/safety, retains unknown completion
clock, and exposes a precise failed owner error. It does not equate success of
unrelated HK/hourly workloads with delivery of this workbench.

Each dynamic module pointer at `<module_root>/<ISO date>/latest.json` is:

```json
{
  "schema":"V4_WORKBENCH_MODULE_COMMIT_V1",
  "module":"execution",
  "date":"2026-10-30",
  "artifact":{"path":"<absolute saved artifact>","sha256":"<sha>"},
  "receipt":{"path":"<absolute saved receipt>","sha256":"<sha>"},
  "RESEARCH_ONLY":true,"production_allowed":false,"buy_gate_updated":false,"orders_sent":false
}
```

Receipt: `status=COMMITTED`, identical `artifact` ref, four flags. For statistics
use module `statistics` and the research source date; execution uses observation
date. The original completion owner advances a pointer only after saving its
artifact and receipt. Versions are content identities, not schedule ticks.

Execution artifact: `observation_date`, `nodes` keyed by original numeric plan
ID; each has `status`, `recorded_at`, `source_asof`, `materials:[{label,url}]`,
`missing:[string]`, `error`, `evidence:[{path,sha256}]`. Bad refs are isolated.

## One-shot caller configuration and invocation

```json
{
  "schema":"V4_WORKBENCH_SLOT_CONFIG_V1",
  "product_root":"<same accepted daily_products/a_share>",
  "state_root":"<host observation_root>",
  "host_binding":{"path":"<private binding>","sha256":"<sha>"},
  "calendar":{"path":"<original market_calendar_2026.json>","sha256":"<sha>"},
  "official_input_root":"<original receipts/a_sync_authority/official_daily>",
  "korea_raw":{"2026-10-30":{"^KS11":{"path":"<saved raw>","sha256":"<sha>"},"^KQ11":{"path":"<saved raw>","sha256":"<sha>"}}},
  "RESEARCH_ONLY":true,"production_allowed":false,"buy_gate_updated":false,"orders_sent":false
}
```

```sh
"$PANEL_PYTHON" -B -m ops.run_workbench_observation_slot --config "$CONFIG" --config-sha256 "$CONFIG_SHA"
"$PANEL_PYTHON" -B -m ops.run_workbench_observation_slot --config "$CONFIG" --config-sha256 "$CONFIG_SHA" --manual-current
```

Run from the installed app root. Natural slots are08:00/08:10/09:15/09:25,
09:30–11:30 and13:00–15:00 every10minutes, plus saved-result checks at
15:40/16:10/16:40/17:00/19:00. No lunch capture, missed-node backfill or clock
substitution. Manual runs are labelled manual. Actual market calendar resolves
previous source session and next slot; an out-of-range calendar, missing source
product or mismatched observation binding fails closed, including year rollover.

An exclusive capture lock prevents overlap. Complete slot refs are reused;
partial slots retain successful items and retry missing ones at most twice.
After two attempts the result is `DIAGNOSIS_REQUIRED`. Content-addressed attempt
artifacts preserve failure evidence; a publication lock rejects an older
completion instead of rolling back the latest pointer. Return status
`PARTIAL_STORED_INTRADAY_SOURCE_BLOCKED` is a saved partial result, not a data PASS.

Daily archive rows carry `capture_kind=OFFICIAL_DAILY_ARCHIVE`,
`source_asof=null`, `source_asof_precision=DATE_ONLY`, source date, prices in CNY,
amount in CNY and original native shares. Date-only archive display/sorting is
handled in our local wrapper; fixed Dot source is unchanged. It is never labelled
real-time or a valid new formula/research panel.

Outstanding: actual installation, live API/browser readback, execution-event
refresh evidence, future natural source delivery, D30 panel SOP repair, Japanese
automatic access and date-certified intraday cumulative quotes. Do not claim
`NATURAL_VERIFIED` until those exact boundaries have actual evidence.
