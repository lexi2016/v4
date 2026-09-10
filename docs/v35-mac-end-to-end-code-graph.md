# V3.5 Mac producer-to-page code graph

This graph is generated from the current V3.5 entry points and contracts. It
describes ownership and evidence flow; a `READY` receipt is never substituted
for an artifact, pointer, API response, or page observation.

## Runtime ownership

```text
legacy V3 / shared producer
        │ exact-date artifact + manifest + receipt
        ▼
V3.5 adapter or consumer
        │ validated JSON receipt / immutable pool artifact
        ▼
state/data current or dated pointer
        │ API consumer
        ▼
8873 backend API
        │ date + stage query
        ▼
V3.5 web UI
```

The Stage Center remains the only raw stage-selection producer. The research
panel lane remains the A/H panel producer. Review Core remains the owner of
ReviewBundle, public-fupan and Stage7 evidence. The V3.5 scheduler only
orchestrates those existing owners and records their typed result; it does not
recompute or impersonate them.

## Scheduled entry points

The authoritative legacy-derived times are registered in
`contracts/runtime_workloads.json` and dispatched by
`infrastructure/scheduling/executor_registry.py`:

| Time | V3.5 workload | Existing entry point | Evidence boundary |
| --- | --- | --- | --- |
| 09:01 / 20:01 | `wechat_preselection_sync` | `ops.wechat_preselection_sync` (consumer-side exact-pair sync) | canonical producer is the legacy `wechat-account-new-article-poll`/`wechat_pipeline_runner sync -> wechat_publish_v35_preselection.py` chain after an exact URL; missing or partial input is retryable `CANNOT_CONFIRM`/`URL_REQUIRED`, never a scheduler-produced pair |
| 17:00 | `research_panel_daily_a` | Existing formal `com.lexi.research-panel.daily` label, `ops.macos_research_panel_daily.py --lane A` | exact formal authority-chain arguments; dated A receipt is the producer evidence; the unified scheduler must supersede the old 60-second label before deployment |
| 17:20 | `research_panel_daily_hk` | Existing formal `com.lexi.research-panel.daily` label, `ops.macos_research_panel_daily.py --lane HK` | exact formal authority-chain arguments; dated HK receipt is the producer evidence; the unified scheduler must supersede the old 60-second label before deployment |
| 17:30 | `research_panel_runtime_evidence` | `ops.publish_research_panel_runtime_receipt` | dated A/H producer receipts, selector/backtest pointers and dated close-review receipt |
| 21:15 | `review_core_pool_pipeline` | `ops.run_review_core_natural_pool_pipeline` | explicit calendar, previous HK date, next A date, package roots and Review Core provenance |

The scheduler's `ALL_SLOTS`, `compute_dates` and
`resolve_due_slot` are in `ops/run_scheduled_slot.py` and
`ops/run_v35_macos_scheduler.py`. The 09:01 workload keeps the business date;
20:01 and 21:15 use the next eligible target date. A bounded 300-second heartbeat can recover a
missed exact slot; ledger claims and dated receipts make the retry idempotent.
The fixed slot order is chronological through the research-panel chain:
`17:00 -> 17:10 -> 17:20 -> 17:30`. A retryable 15:00 failure cannot consume
an exact 17:00/17:20 producer wake; the 17:30 publisher remains dependency-
ordered catch-up after both producer lanes.

The 17:00/17:20 producer lanes reuse the already-proven formal research-panel
entry and its full authority argument set. They are not a second collector. A
future formal install must atomically replace or disable
`com.lexi.research-panel.daily` before enabling these two unified-scheduler
workloads; the candidate batch intentionally performs no install or service
action.

The 20:25 Review Core acquisition owner is intentionally not taken over by
these workloads. It remains a separate owner in the V3 graph until its own
Mac runtime is proven.

## Research panel lineage

```text
com.lexi.research-panel.daily (existing formal owner; superseded at deploy)
  └─ ops/macos_research_panel_daily.py --lane A @ 17:00
  └─ ops/macos_research_panel_daily.py --lane HK @ 17:20
  └─ state/research_panel_daily/receipts/{A,HK}-{date}.json
       ├─ selector pointer: state/workspace/数据/data_layer_interface_current/
       │                    CURRENT_SELECTOR_READY_PANEL.txt
       ├─ backtest pointer: state/workspace/数据/backtest_panel_interface_current/
       │                    CURRENT_BACKTEST_BASE_PANEL.txt
       └─ close review + receipt: state/data/close_reviews/{date}.json
                                  state/data/receipts/close_reviews/{date}.json
              │
              ▼
ops/publish_research_panel_runtime_receipt.py
  └─ state/data/runtime_graph/evidence/research_panel_status/{date}/
       ashare_research_panel.json
       hkconnect_research_panel.json
              │
              ▼
ops/collect_runtime_graph.py → infrastructure/runtime_graph/service.py
              │
              ▼
runtime graph API and 8873 observability panels
```

The publisher is a lineage publisher only. If the A authority is still
`REBUILD_REQUIRED`, it reports `PARTIAL`/`CANNOT_CONFIRM` and does not promote
that lane. The HK lane is evaluated independently.

## WeChat exact-pair lineage

```text
canonical V3 WeChat producer (exact URL verified)
  ├─ wechat-account-new-article-poll (profile hint / typed receipt only)
  └─ wechat_pipeline_runner sync -> wechat_publish_v35_preselection.py
        │
        ▼
verified V3 WeChat run
  ├─ wechat_manifest.json
  └─ wechat_rows.csv
        │ exact effective date + SHA/schema/date/safety validation
        ▼
ops/wechat_preselection_sync.py
        │
        ├─ state/data/preselection_pools/{date}/wechat_public_account_v3_preselect.json
        └─ state/data/preselection_pools/{date}/receipts/...
              │
              ▼
preselection API → 8873 D-1 / research view
```

The future scheduler input binding is the single source root
`state/data/preselection_inputs/{effective_date}` (or an explicit
`V35_WECHAT_INPUT_ROOT` under that root); it is kept separate from the output
store `state/data/preselection_pools/{effective_date}`. The historical
`state/data/preselection_pools/20260821/wechat_{manifest,rows}` pair is
evidence-only/one-time canary input and is not a natural-production fallback.
The sync does not enumerate another date, infer a filename suffix, or create a
run when the pair is missing. A `CANNOT_CONFIRM`/`URL_REQUIRED` sync is emitted
as a typed retryable failure, not a successful scheduler lane; the bounded
heartbeat may retry it after the exact pair is published. The scheduler never
claims the profile poll or the legacy exact-pair producer as its own.

## Review Core natural pool lineage

```text
20:25 Review Core acquisition owner (separate)
        │
        ▼
ops/run_review_core_natural_pool_pipeline.py @ 21:15
        │ review_core.pool_pipeline (non-shell, explicit roots)
        ├─ HK close review
        ├─ public fupan pool
        └─ Stage7 pool
              │ run_id + artifact/manifest/receipt SHA
              ▼
Review Core shared store / current pointer
              │
              ▼
preselection API + 8873 review/pool panels
```

The adapter returns `PARTIAL` or `CANNOT_CONFIRM` when any required workload
or provenance is incomplete. Existing public fupan evidence can therefore be
shown without fabricating Stage7 or video evidence.

## LaunchAgent contract

`ops/install_v35_macos_launchagents.py` renders two deterministic payloads:

* `com.lexi.v35.scheduler`: exact calendar intervals plus
  `StartInterval=300` for bounded catch-up. It is the business dispatcher.
* `com.lexi.v35.runtime-graph`: a separate observability-only one-shot
  collector with the same 300-second heartbeat. It carries
  `V35_OBSERVABILITY_ONLY=true` and cannot be treated as a producer receipt.

Both payloads carry the three safety flags as false. This candidate only
renders release-owned artifacts under the permitted Mac roots; it does not
perform a formal LaunchAgent cutover.
