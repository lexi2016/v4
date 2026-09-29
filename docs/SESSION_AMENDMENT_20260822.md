# V3.5 session amendment — 2026-08-22

This amendment records the reuse boundary for the scheduler integration batch.
It is evidence-only documentation; it does not install a LaunchAgent, restart a
service, or change formal Application Support state.

## REUSE_PREFLIGHT

- Active integration root (the only candidate worktree):
  `/Users/lexi/Documents/Codex/2026-08-13/v35-stage-selection-20260821-fix/release-candidate/app`.
- The legacy V3 graph is read-only design/provenance input. The scheduler reuses
  the existing V3.5 adapters and stores; it does not recreate shared collectors,
  Review Core, the WeChat producer, or Stage7 raw data.
- WeChat is split into two owners: the 09:01/20:01 profile poll is a hint/typed
  receipt only; an exact URL is required before the legacy
  `wechat_pipeline_runner sync -> wechat_publish_v35_preselection.py` producer
  can publish `wechat_manifest.json` and `wechat_rows.csv`. The future V3.5
  workload reads the exact pair from
  `state/data/preselection_inputs/{effective_date}` and writes the materialized
  output to the separate `state/data/preselection_pools/{effective_date}`
  store. The historical
  `state/data/preselection_pools/20260821/wechat_{manifest,rows}` pair is
  evidence-only/one-time canary input and is not a natural fallback. The
  workload never probes another date or invents the pair. Missing input is
  `URL_REQUIRED`/`CANNOT_CONFIRM` and is retryable, not a successful receipt.
- Review Core acquisition at 20:25 remains a separate owner. The 21:15
  `ReviewCore_Pools_2115` workload does not take over acquisition and remains
  separate from `FUPAN_8771_VERIFY`.
- The runtime graph collector is observability-only. A graph snapshot or
  collector receipt cannot be used as a business producer or as evidence that a
  pool is READY.
- The three safety flags remain false in every scheduler result and test:
  `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.
- Read-only formal LaunchAgent preflight found the existing producer label
  `com.lexi.research-panel.daily` with `ops/macos_research_panel_daily.py
  --lane ALL`, `StartInterval=60`, and dated A/H receipts through 20260821.
  The canonical lane owners are A=`OpeningAdvisorV3_1700_AshareResearchPanel`
  and HK=`OpeningAdvisorV3_1720_HKConnectResearchPanel`; the unified candidate
  scheduler now dispatches the same entry with the exact proven authority
  arguments at 17:00/17:20. A deployment must supersede the old 60-second
  producer label before enabling these two scheduler workloads; this batch
  deliberately does not install or stop either label, so no duplicate producer
  is claimed.
- The candidate plist renderer rejects an incomplete binding and emits the
  launch shell, every shell root, release/fingerprint identity, explicit
  research-panel authority paths, and all executor-read `V35_REVIEW_CORE_*`
  roots. Date-specific close-review paths remain derived from the dispatch
  business date and are not frozen into a persistent plist.
- Evidence-only/superseded roots, never writable in this batch:
  `/Users/lexi/Documents/Codex/2026-08-13/v35-stage-selection-20260813`,
  `/Users/lexi/Documents/Codex/2026-08-13/v35-stage-selection-finance-localize-20260817`,
  `/Users/lexi/Documents/Codex/2026-08-13/v35-stage-selection-hourly-20260817`,
  `/Users/lexi/Documents/Codex/2026-08-13/v35-stage-selection-publish-chain-repair-20260819`,
  `/Users/lexi/Documents/Codex/2026-08-13/v35-stage-selection-research-depth-20260817`,
  `/Users/lexi/Documents/Codex/2026-08-13/v35-stage-selection-research-quality-retry-20260817`,
  `/Users/lexi/Documents/Codex/2026-08-13/v35-019ff6cd`.
- `/Users/lexi/Desktop/学习/**` is read-only context and is not a candidate
  write root.
- Boundary incident recorded for audit: approximately 11:13–11:17 an early UI
  agent wrote the seven Desktop-tree files
  `apps/web/src/App.spec.ts`, `apps/web/src/App.vue`,
  `apps/web/src/components/research/ResearchFeedCard.vue`,
  `apps/web/src/components/research/ResearchSourceColumns.vue`,
  `apps/web/src/composables/useResearchLane.ts`,
  `apps/web/src/views/ResearchView.spec.ts`, and
  `apps/web/src/views/ResearchView.vue`. Approximately 11:30–11:34 another
  agent wrote Desktop-tree `ops/wechat_preselection_sync.py`,
  `ops/wechat_probe.py`, and `tests/test_wechat_probe_and_sync.py`, with
  related `tests/__pycache__/test_preselection_optional_pools*.pyc`,
  `test_preselection_slice*.pyc`, and `test_wechat_probe_and_sync*.pyc`.
  These bytes are incident evidence only and are excluded from candidate
  delivery; Sol did not revert, delete, or overwrite them, and no Desktop bytes
  were copied into the active Documents candidate.

## Owner matrix

`CANNOT_CONFIRM` means the current candidate graph has not proven a live
artifact/pointer at that layer. It is intentionally not filled with a date from
another run.

| canonical_task | stage/slot | unique producer | unique writer/worktree | artifact | receipt | current | API/page consumer | next natural slot |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `wechat-account-new-article-poll` | 09:01 / 20:01 | Legacy V3 profile poll; exact-pair producer remains the exact-URL `wechat_pipeline_runner sync -> wechat_publish_v35_preselection.py` chain | Producer writer/worktree: `CANNOT_CONFIRM`; scheduler adapter writer: Luna Max / active candidate root | Future exact `state/data/preselection_inputs/{date}/wechat_{manifest,rows}` pair; historical `preselection_pools/20260821` pair is superseded evidence | Typed poll/producer receipt: `CANNOT_CONFIRM` until exact URL/pair is verified | Output manifest `state/data/preselection_pools/{date}/manifest.json` only after consumer materialization; live current: `CANNOT_CONFIRM` | `/api/v3/preselection-pools?date=...`; 8873 D-1 / research view | 09:01 / 20:01 next eligible day |
| `wechat_preselection_sync` | 09:01 / 20:01 | Existing verified WeChat pair; scheduler is a consumer, not the producer | Luna Max / active candidate root | `state/data/preselection_pools/{date}/wechat_public_account_v3_preselect.json` | Store receipt under `preselection_pools/{date}/receipts/`; scheduler receipt under `receipts/wechat_preselection/{date}.json` | Dated manifest is the only current binding; live READY: `CANNOT_CONFIRM` | `/api/v3/preselection-pools`; 8873 D-1 / research view | 09:01 / 20:01 next eligible day |
| `OpeningAdvisorV3_1700_AshareResearchPanel` | 17:00 A-share post-close lane | Existing formal `com.lexi.research-panel.daily` producer, same `ops/macos_research_panel_daily.py --lane A` entry and authority args | Existing formal producer owner; unified candidate scheduler adapter writer: Luna Max / active candidate root; deployment must supersede old 60s label | `state/research_panel_daily/receipts/A-{date}.json` | Dated A producer receipt plus selector/backtest/close-review inputs | A receipt current through 20260821 in read-only preflight; future natural slot `CANNOT_CONFIRM` until deployment | `/api/v3/research/lane`; 8873 研报决策台 | 17:00 next eligible A-share day |
| `OpeningAdvisorV3_1720_HKConnectResearchPanel` | 17:20 HK Connect post-close lane | Existing formal `com.lexi.research-panel.daily` producer, same `ops/macos_research_panel_daily.py --lane HK` entry and authority args | Existing formal producer owner; unified candidate scheduler adapter writer: Luna Max / active candidate root; deployment must supersede old 60s label | `state/research_panel_daily/receipts/HK-{date}.json` | Dated HK producer receipt plus HK 0.2 authority receipt | HK receipt current through 20260821 in read-only preflight; future natural slot `CANNOT_CONFIRM` until deployment | `/api/v3/research/lane`; 8873 研报决策台 | 17:20 next eligible HK Connect day |
| `research_panel_runtime_evidence` | 17:30 post-close | Existing A/H daily producer receipts; publisher only projects verified evidence | Luna Max / active candidate root | `state/data/runtime_graph/evidence/research_panel_status/{date}/{ashare,hkconnect}_research_panel.json` | Publisher receipt fields in the two dated evidence files; scheduler dispatch receipt | No formal current pointer proven; `CANNOT_CONFIRM` | `/api/v3/research/lane`; 8873 研报决策台 | 17:30 next eligible trading day |
| `ReviewCore_Acquisition` | 20:25 | Independent Review Core acquisition owner | Producer writer/worktree: `CANNOT_CONFIRM`; not owned by this scheduler | ReviewBundle/acquisition shared-store artifact: `CANNOT_CONFIRM` | Acquisition receipt: `CANNOT_CONFIRM` | `CANNOT_CONFIRM` | `/api/v3/preselection-pools` review lanes; 8873 D-1 / review panels | 20:25 next eligible day |
| `ReviewCore_Pools_2115` | 21:15 | Official Review Core `pool_pipeline` for fupan/Stage7/HK lanes, after the independent acquisition owner | Luna Max / active candidate root for the wrapper; official producer writer/worktree `CANNOT_CONFIRM` | Review Core shared-store pool artifacts under explicit `V35_REVIEW_CORE_*` roots; canary fupan `PARTIAL` 54 rows (`DAILY_VIDEO_NOT_LOCKED`), HK `PARTIAL`, Stage7 `CANNOT_CONFIRM` 0 | Official exit 0 plus adapter exit 2 / `CANNOT_CONFIRM` at `/Users/lexi/Documents/Codex/2026-08-13/v35-stage-selection-20260821-fix/test-tmp/reviewcore-natural-sol`; symlink package root rejected, resolved immutable release root accepted | Shared-store current pointer: `CANNOT_CONFIRM`; Stage7 `no latest run for 20260821 / A_SHARE_1MIN_STAGE_1445_1500` | `/api/v3/preselection-pools`; 8873 D-1 / review panels | 21:15 next eligible day |
| `FUPAN_8771_VERIFY` | 21:15 | Separate V3.5 close-review verify owner; not `ReviewCore_Pools_2115` | Luna Max / active candidate root for dispatch adapter; upstream producer `CANNOT_CONFIRM` | `runtime_graph/evidence/node_action_status/{date}/FUPAN_8771_VERIFY.json` | Node action/HTTP page receipt: `CANNOT_CONFIRM` | `CANNOT_CONFIRM` | `/api/v3/review?date=...`; 8873 A股复盘 | 21:15 next eligible day |
| `A_SHARE_STAGE_1445_1500` / Stage7 raw19 | 15:00 | Existing Stage7 1-minute raw producer; current exact raw19 source is missing | Producer writer/worktree: `CANNOT_CONFIRM`; no adapter may synthesize normalized rows | Exact Stage7 raw19 artifact: `CANNOT_CONFIRM` | Stage7 manifest/receipt: `CANNOT_CONFIRM` | `CANNOT_CONFIRM` | `/api/v3/preselection-pools`; 8873 D-1 Stage7 panel | 15:00 next eligible day |
| `runtime_graph_observability` | Every 300 seconds bounded heartbeat | `ops.collect_runtime_graph.py` (observability only) | Luna Max / active candidate root for LaunchAgent generator | Runtime graph snapshot/state collector output | `runtime_graph/state/collector_receipt.json`: live `CANNOT_CONFIRM` | No business current pointer; `CANNOT_CONFIRM` | Runtime-graph API routes; 8873 运行图谱 | Every 300 seconds; not a business slot |

## Scheduler semantics fixed in this batch

The calendar plist has exact fixed slots and a bounded `StartInterval=300`
catch-up. The 09:01 WeChat probe/sync keeps `target_date=business_date`; the
20:01 sync and 21:15 pool pipeline use the next eligible target date.
Retryable `UPSTREAM_NOT_READY`/`EXTERNAL_SOURCE` failures release claims and
carry a five-minute `retry_after`; only exit-0 semantic `READY` results close a
new WeChat or Review Core lane. A research-panel publisher may close with
A=`PARTIAL` and HK=`READY`, while retaining `evidence_status=PARTIAL`.
The fixed catalog keeps the producer order `17:00 -> 17:20 -> 17:30`.
At an exact 17:00 or 17:20 wake, the current research-panel producer has
fairness priority over an older retryable 15:00 receipt; at 17:30 the ordered
catch-up still requires both producer lanes before publishing runtime evidence.
