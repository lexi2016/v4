# Research source unification — 2026-10-15 R3

Scope: research frontend source/runtime convergence and hourly-domain globals removal. Manager and WeChat implementations are excluded. No new service, producer, framework, adapter, or forwarding module was added. Historical inputs, payloads and receipts are not rewritten.

## Baseline and source identity

- Canonical: `/Users/lexi/Desktop/学习/v4_app`, local HEAD `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`; existing dirty changes were preserved. This turn is compared with frozen file preimages, not all differences from HEAD.
- Private remote base: `794d47ce2499d167e1faa0da5139f5d60a90731f` in `lexi2016/v4`.
- API base: `hk-auto-execution-audit-api-20261015-r4`.
- Initial scheduler control: `hk-history-adjudication-scheduler-20261015-r3`. Another task changed the live scheduler binding during this work to `hk-close-backfill-reader-main-20261015-r1` (plist SHA256 `308660c7ab1d3fe56c2b641d2910bed51a4351bcfaa170f1d6aee0055d6cc4b0`). This task does not write or restart the scheduler. API activation protects the latest scheduler bytes and PID captured immediately before activation; it does not restore the initial scheduler.
- Local evidence root: `/Users/lexi/Desktop/学习/agents调试/V4_RESEARCH_CONSOLIDATION_20261015_R3` (referred to below as R3). Raw API responses, browser text and plist backups stay local.

## Batch 1 — frontend

Six runtime files differed from canonical. The merge uses the existing composable and components:

| File | Result |
| --- | --- |
| `apps/web/src/composables/useResearchLane.ts` | Keeps eligible research subjects in the stock mainline and retains other entities/title subjects as visible evidence; preserves exact/latest and stale-response guards. |
| `apps/web/src/views/ResearchView.vue` | Connects the existing subject/entity display; keeps the three-column research flow. |
| `apps/web/src/components/research/ResearchImpactList.vue` | Retains subject eligibility and source-entity evidence in the existing component. |
| `apps/web/src/components/research/ResearchFeedCard.vue` | Preserves title → source_title → stock_name → stock_code priority and entity role, real source times and unknown evidence. |
| `apps/web/src/components/research/ResearchFeedPane.vue` | Keeps the complete feed and existing ordering; no 42-card truncation. |
| `apps/web/src/components/research/ResearchSourceColumns.vue` | Canonical already had correct empty-message handling; runtime receives those exact bytes, with no canonical edit. |

`ResearchView.spec.ts` adds coverage for eligible, ineligible and unclassified entities, title subjects, entity roles and title priority. No new business module was introduced. All 12 frozen research runtime sources match canonical byte-for-byte in the candidate. Non-target source and standalone manager/daily entry assets remain unchanged.

Independent Batch 1 acceptance: 41 research specs, 3 frontend API contract specs and 3 focused EXACT/LATEST route tests passed; build passed. Typecheck still exits 2 with the same 34 preexisting diagnostics, without new diagnostics. Receipt: `R3/batch1-reviewer/receipt.json`.

Batch 1 remote commit: `22743f92170462067430fce21d037663fe79eeff`; all six changed remote files were read back and matched exact local bytes and Git blob SHA.

## Batch 2 — direct hourly-domain implementation

`domains/research_hourly.py` now directly implements these 12 former forwarding functions:

- `build_raw_items`, `normalize_research_items`, `stock_aliases`, `_receipt_entity`
- `unassigned_entity_notes`, `normalized_source_evidence_level`, `extract_stock_evidence`
- `aggregate_stock_research_daily`, `build_research_pool_bridge`, `build_research_lane_snapshot`
- `write_snapshot_outputs`, `project_hourly_stage_fields`

Removed source files under `domains/_research_hourly_parts/`: `__init__.py`, `_namespace.py`, `lane_snapshot.py`, `research_projection.py`, `rows_topics.py`, `source_evidence.py`.

This removes the scope dictionary forwarding and dynamic global-name resolution. The six deleted files contained 561 lines; after moving the required implementation into the public module, total scoped source falls from 1,028 to 929 lines: **99 net lines removed**. Public signatures remain unchanged. No active source consumer references the removed modules. Historical handoff copies and a non-importable preexisting bytecode cache remain outside the source cleanup.

Final domain SHA256: `574f106bc2156cc8abc3c9fa37f19b2d8f65cd7e5a5b05b1fd2b77dc5d83a515`. The existing runner identity already hashes this executed module, so neither an identity wrapper nor a manifest/runner edit is needed.

The frozen and new canonical implementations match for the full snapshot, hourly stage projection, and all eight serialized outputs with a fixed execution clock. Source times, receipt SHA, status, unknown reasons and safety fields are compared, not excluded.

## Deliberately preserved differences and failures

- Scheduler domain is already direct, without globals. It additionally calls `apply_report_subject_policy(payload)` and lacks five API stage helpers. This existing business difference is preserved; the scheduler is not overwritten or redeployed. This work does **not** claim three-way domain source equality.
- Canonical research-lane tests have one unchanged failure: `test_lane_router_projects_us_session_capture_provenance`, `invalid research peripheral capture fields`. Both frozen and new canonical produce 31 passes and the same failure. Peripheral-store repair is outside this batch.
- The independent reviewer ran current workspace tests against writable copies of the **complete** API base and candidate releases: both produce 30 passes and the same 20 failures, from the unchanged older collector API (`manual_recovery` unsupported / READY_EMPTY behavior). Candidate-owned hourly runner and regression tests pass 23/23 against the actual candidate import path. The writer’s earlier 12-failure/8-pass PIT result used a three-file overlay with canonical dependencies; it is retained as partial-overlay evidence, not as the complete runtime verdict. Canonical focused tests, including ready-empty, independently pass 50/50. No collector/runner repair is included here; this does not prove a natural empty-slot run.
- Missing/unknown times and unassessed counts remain explicit; no timestamps or zero counts are invented.

## Release and acceptance

Combined immutable API candidate: `research-source-unified-api-20261015-r3`, manifest SHA256 `cc0766ae58036d82e2a9ff0e3c87c51d7fcacf9c9f50c66e2186eb4553abc759`.

The release delta is six frontend sources, `domains/research_hourly.py`, `apps/web/dist/index.html` and its new main JavaScript asset. Other bytes are preserved. Build output is deployed locally but excluded from GitHub synchronization.

Batch 2 independent verdict: PASS for the frozen source and actual candidate envelope. Canonical focused tests passed 50/50; actual candidate native hourly tests passed 23/23. The complete-release baseline failures above remain explicit.

Batch 2 remote commit: `bfe203881066782fa25bdb20d374fd7a382ef78e`. The main file was read back byte-for-byte, and all six deleted source paths were confirmed absent from the remote tree.

The deployed final API release is **`research-source-unified-api-20261015-r6`**, manifest SHA256 `a6eb7c96ef0bd5c449146176dbcfefc927f3df06ca64b9b02de9c0715e56c617`, process PID 73796 at activation. It incorporates a separately reviewed CSS-only follow-up: source-column and main-feed empty states share `overflow-wrap: anywhere`, preserving long diagnostic codes without clipping. Final CSS SHA256 is `2abbfd90773ec69ba3da7f8c735a54a0268245c23d39f9ffaa683440dae81a16`. Independent rebuilt assets match this release; standalone manager and daily entry assets are unchanged. All 13 research runtime source files match canonical, recorded in the adjacent identity JSON.

API verification after activation: exact 20261012 and 20261015 lane bindings are correct; production/buy/order flags are false. The 20261012/1700 response retains SHA256 `22186513df8c44a25068f996479143d23a7e3f9ede28d7b4965acf9570403909`; the 20261012 day product retains `888e973d083d27457cde4b617748dc8a9b0ea6491d4d77b26edf22fae330ace6`. Both match the original raw response bytes. Latest scheduler PID and plist bytes were identical immediately before/after each API-only switch; no scheduler restart or rollback occurred.

Built-in browser verification: original 20261012 page shows 50 main-feed cards (not truncated to 42); title and entity evidence expand correctly; selected-date EXACT, explicit LATEST with actual-source-date warning, return-to-EXACT and rapid date switching were checked. At 390px, all seven research filters (all, morning, stock, ZSXQ, finance, AI, priority) have no research-area horizontal overflow. AI and priority empty states retain their real diagnostics. At 1280px the three panes share the same top coordinate and remain side by side, with no document overflow. The temporary viewport override was reset. Manager and WeChat flows were not exercised or modified.

Retained UI issue: the common application header `runtime-badge` still exceeds a 390px viewport. Its global styling is outside this bounded research change. Historic missing timestamps and unknown source timezones remain unknown; no history was fabricated. An intermediate R4 candidate had an incorrect build-directory selection, was caught before activation and never deployed; the corrected release assets were independently checked.

States: `IMPLEMENTED`, `REVIEWED`, scoped `TESTED`, `DEPLOYED`, `API_VERIFIED`, and research-scope `UI_VERIFIED`. Natural execution remains `NATURAL_SLOT_UNVERIFIED`; displaying a naturally updated row is not substituted for a full natural-slot receipt.

Evidence: `R3/batch1-reviewer/receipt.json`, `R3/batch2-reviewer/receipt.json`, `R3/batch1-narrow-reviewer/receipt-r2.json`, `R3/narrow2/controller/activation-receipt.json`, `R3/ui/ui-receipt.json`. Only source, necessary tests, this summary and source identities are synchronized to the private branch; business data, raw responses, plist backups, screenshots and dist stay local.
