# Issue #30: read-only source ownership and boundary audit

Input: `lexi2016/v4` commit `f615f4edcf4eb57aa6cf9ab407f2c2c2ed329a9b`, directory `handoff/8873-module-isolation-issue-20261010-r1`.

Scope: static source inspection and AST route extraction. No application imports, production/test source edits, service calls, state reads, deployment, or Mac verification were performed. This report is a proposal for the implementation/reviewer, not confirmation of a live owner contract.

## Conclusion

The snapshot proves several router composition boundaries, but **does not prove any approved business `module_id` → unique source owner → complete dependency/state/build closure**. Real module owner records should remain `CANNOT_CONFIRM` and non-publishable until an explicit, SHA-bound runtime contract supplies that missing authority. Synthetic owners A/B may exercise the release mechanism without promoting their labels or fixture paths into production facts.

This distinction is required by [CHAT_TASK.md](sandbox:/workspace/scratch/a245cda1e07c/input/CHAT_TASK.md), “实施前冻结” item 3, and [MODULE_MAP.json](sandbox:/workspace/scratch/a245cda1e07c/input/MODULE_MAP.json), `status`, `observed_route_groups`, and `workspace_directory_mapping`. None of `助手`, `数据`, `个股`, `牛股学习`, or `Z哥方法论` supplies code-ownership evidence.

The existing publisher must be extended at its current gateway build and verification call sites. Both `build_integrated_app` and `verify_api_release_candidate` presently call `_assert_role_delta_paths` only for a non-gateway role or bootstrap transition; ordinary gateway deltas therefore lack a business owner check. Existing `gateway`/`stage`/`manager` are service roles, including ports 8873/8874/8875, not business owners. See [api_release_integration.py](sandbox:/workspace/scratch/a245cda1e07c/input/source/canonical-worktree/ops/api_release_integration.py), those functions and `module_role_contract`, and [api_module_contracts.json](sandbox:/workspace/scratch/a245cda1e07c/input/source/canonical-worktree/deployment/api_module_contracts.json), `roles`.

## Small owner/path proposal

The following are **candidate labels for owner review**, not accepted owner assignments. Paths are app-relative. Start with exact enumerated files; do not grant entire `infrastructure/**`, `contracts/**`, or `v4/**` trees merely because one router imports them.

| Proposed review label | Evidenced initial source boundary | Route evidence / material limitation |
| --- | --- | --- |
| `preselection` | `apps/api/v35_api/preselection_router.py`, `preselection_service.py` | `create_preselection_router` exposes GET `/api/v3/preselection-pools`; the service imports domain, store, calendar and trading-safety contracts. Stage-related changes remain suspended by task scope. |
| `manager_research` | `apps/api/v35_api/manager_research_router.py` | `create_manager_research_router` registers exact paths beneath `/api/v4/manager/research`. Its implementation imports and calls `v4.manager_research` functionality absent from the runtime-B source subset. |
| `manager_workbench` | `apps/api/v35_api/manager_workbench_router.py` | GET `/api/v4/manager/workbench-research`; `ManagerWorkbenchResearchReader` is also injected into `ManagerResearchJobService` by `app.py`. Treat the coupling as an explicit dependency; independent owner approval is unproven. |
| `research_lane` | `apps/api/v35_api/research_lane_router.py` | GET `/api/v3/research/{lane,dates,us-market,latest-event,events}`. It shares the `/api/v3/research` prefix and research-store dependencies with the legacy research router. |
| `research_archive` | `apps/api/v35_api/research_router.py` | Exact article/day/selection/manager-decision/hourly/authoritative routes, plus an included WeChat router whose source is absent from this snapshot. Prefix ownership is insufficient. |
| `review` | `apps/api/v35_api/review_router.py` | GET `/api/v3/review` and POST `/api/v3/review/generate`; generation writes attempt receipts and invokes an external generation closure. Do not classify the module as read-only. |
| `baimao` | `apps/api/v35_api/baimao_router.py` | GET `/api/v3/baimao/x/latest` and `/api/v3/baimao/observations`; the latter invokes a loader without the injected data root, so its actual state binding requires the missing store source. |
| Platform review, not a business label | `apps/api/v35_api/runtime_router.py`, `runtime_graph_router.py` | Task status and runtime identity consume shared release/ledger evidence; runtime graph exposes POST `/repair`. Protect these as integration/control surfaces pending a separate owner contract. |

Evidence: each named `create_*_router` in [runtime-B API sources](sandbox:/workspace/scratch/a245cda1e07c/input/source/runtime-B-release/apps/api/v35_api); [app.py](sandbox:/workspace/scratch/a245cda1e07c/input/source/runtime-B-release/apps/api/v35_api/app.py), `create_app`, `_load_manager_research_components`, and `_resolve_manager_research_state_root`. These labels are based on source and route names only.

### Contract shape and enforcement

Add a distinct business-owner contract to the current publisher, keeping `service_role = gateway`, label `com.lexi.v35.api-only`, host `127.0.0.1`, port `8873`. The minimal validated record should contain:

| Contract field | Required meaning |
| --- | --- |
| `schema_version`, immutable contract SHA | Version and exact bytes used during candidate construction and again during publication/rollback. |
| `module_id`, `owner_id`, `status` | Explicit stable identity and unique source authority; absent/unconfirmed owners fail closed. The caller cannot authorize itself by inventing an owner name. |
| `owned_paths` | Canonical, app-relative, exact source/output paths with exactly one owner. Reject overlaps, duplicates, symlinks and aliases before copying. |
| `routes` | Complete `(method, path)` inventory and source function binding. Include nested routers and direct `app.py` handlers. |
| `dependencies` | Explicit other-module/shared-interface dependencies with accepted contract/version/SHA evidence; an import is evidence of dependency, not permission to modify the imported file. |
| `shared_paths` / approved integration record | Platform owner plus affected module owners and exact before/after SHAs. Ordinary module releases cannot alter them; a reviewed joint change must be tied to the same base and contract. |
| `build_inputs`, `build_outputs` | Exact inputs and complete output inventory, with shared chunks and HTML edges accounted for. Unknown/dynamic outputs reject. |
| `state_bindings` | Named external bindings, read/write mode, schema compatibility and known consumers. Never bundle the state or use external absolute paths as module source ownership. |

Validate the owner contract and target module both before any candidate write and in the final locked verification, alongside the existing exact-base/inventory/CAS checks. Build from the complete current active immutable app. For reverse deltas, bind each target's expected current SHA and the intended parent bytes; preserve non-target app/static/config bytes and reject incompatible shared dependencies. A candidate-local changed contract must not widen its own allowlist without a separately approved integration contract bound to the active authority.

## Shared surfaces requiring explicit ownership

1. **Gateway composition:** `apps/api/v35_api/app.py` and `run.py`. `create_app` initializes stores, injects readers and environment bindings, registers routers, implements Stage handlers directly, and mounts static output. `/api/v3/manager/stage-selection` is implemented directly in `app.py`; it cannot be assigned by the name of `manager_research_router.py`. The runtime launcher uses `uvicorn.run(create_app(...))` on the same gateway and has explicit Stage-mode validation. Treat edits here as integration changes, while preserving the task's Stage freeze.

2. **Frontend build and shared output:** `apps/web/vite.config.ts`, `package.json`, `package-lock.json`, the three HTML entries, their bootstraps, `src/App.vue`, shared CSS, public contracts, and the complete `apps/web/dist` output. Vite has `main`, `dailyResearchCommand`, and `managerSelection` inputs, but no configured build manifest/output ownership map. The snapshot excludes `dist`; there is no evidence for per-module generated-file ownership or the current chunk graph. `_RevalidatingStaticFiles` in `app.py` explicitly accounts for HTML referencing hashed assets. `copy_dist` in the old helper copies every discovered dist entry. A whole-dist rollback is unsafe for independent modules.

   Source evidence: [vite.config.ts](sandbox:/workspace/scratch/a245cda1e07c/input/source/runtime-B-release/apps/web/vite.config.ts), [package.json](sandbox:/workspace/scratch/a245cda1e07c/input/source/runtime-B-release/apps/web/package.json), [release_candidate_sources.py](sandbox:/workspace/scratch/a245cda1e07c/input/source/canonical-worktree/ops/release_candidate_sources.py), `copy_dist`, and [README.md](sandbox:/workspace/scratch/a245cda1e07c/input/README.md), omitted artifacts. A safe initial API-only module release preserves the entire active dist unchanged; a frontend change needs the explicit build/shared-output contract first.

3. **Cross-entry consumers:** the manager view imports the research-lane API, selection APIs, Stage APIs, and several contracts; the main app imports review/research views and shared components. The daily research command calls both the research-day route and shared date-list route. Three HTML files therefore do not prove three isolated business modules. See [ManagerSelectionView.vue](sandbox:/workspace/scratch/a245cda1e07c/input/source/runtime-B-release/apps/web/src/views/ManagerSelectionView.vue), imports; [App.vue](sandbox:/workspace/scratch/a245cda1e07c/input/source/runtime-B-release/apps/web/src/App.vue), imports; and [DailyResearchCommandView.vue](sandbox:/workspace/scratch/a245cda1e07c/input/source/runtime-B-release/apps/web/src/views/DailyResearchCommandView.vue), request functions.

4. **Public contracts/config and release identity:** Python `contracts/*`, TypeScript `src/contracts/*`, dependency configuration, router registries, release manifests, the complete app inventory, active pointer/generation, and launch identity need explicit integration ownership. This is a protective classification; the partial snapshot does not establish every co-writer or identify the final platform owner.

## State boundaries: observed bindings, not a verified state inventory

| Consumer | Observed source binding | Unresolved boundary |
| --- | --- | --- |
| Gateway/common stores | `create_app(data_root)` → `NativeDataStore`; launcher argument or `V35_DATA_ROOT` | Live root, complete writer list and storage implementation absent. |
| Preselection / Stage consumers | `V35_PRESELECTION_SOURCE_ROOT`, `V35_STAGE_CENTER_SELECTION_ROOT`, optional shared-data root | Source resolution may vary by date; Stage producers and state remain outside this task. |
| Research archive/lane | `V35_RESEARCH_DATA_ROOT`, research ledger or dispatcher fallback; morning-news binding; US-market read bound to common data root | Separate read root does not move the V4 selection/materialization owner. `research_router` keeps `ResearchSelectionStore(data_root)` and WeChat material path under the common root. |
| Manager research/workbench | explicit argument, then `V4_MANAGER_RESEARCH_STATE_ROOT`, then canonical/fallback state root; `materials` and `workbench_research` children | Shared reader/service coupling and missing `v4/manager_research` closure prevent a complete read/write/rollback compatibility proof. |
| Review generation | `V4_DAILY_REVIEW_ROOT`, SHA-bound generation bindings/config and `runtime.state_root` | `_manual_generate` writes `manual_generation/<date>.json` and invokes `run_generation`; source-only rollback cannot undo these writes or prove older code can consume them. |
| Runtime status/graph | common data root, dispatcher ledger, selected allowlisted release env keys and fixed API plist locator | Missing `RuntimeGraphService` and repair-controller closure; repair is a control-plane operation. |
| Baimao observation loader | `load_baimao_research_observations(source_date)` | No root passed here; loader implementation and active binding required. |

Evidence: [app.py](sandbox:/workspace/scratch/a245cda1e07c/input/source/runtime-B-release/apps/api/v35_api/app.py), initialization and router injection; [run.py](sandbox:/workspace/scratch/a245cda1e07c/input/source/runtime-B-release/apps/api/v35_api/run.py), `main`; [research_router.py](sandbox:/workspace/scratch/a245cda1e07c/input/source/runtime-B-release/apps/api/v35_api/research_router.py), `create_research_router`; [review_router.py](sandbox:/workspace/scratch/a245cda1e07c/input/source/runtime-B-release/apps/api/v35_api/review_router.py), `_manual_generate`; [runtime_graph_router.py](sandbox:/workspace/scratch/a245cda1e07c/input/source/runtime-B-release/apps/api/v35_api/runtime_graph_router.py), `create_runtime_graph_router` and `API_PLIST_PATH`; [baimao_router.py](sandbox:/workspace/scratch/a245cda1e07c/input/source/runtime-B-release/apps/api/v35_api/baimao_router.py), `baimao_observations`.

## Negative and preservation tests to require

These are proposed acceptance cases, not tests executed by this audit. Use isolated synthetic files and state only; stable error names below are recommendations.

| Case | Required fail-closed/preservation assertion |
| --- | --- |
| Unknown module, missing owner, unconfirmed owner, missing contract, altered contract SHA | Reject before copying/reloading: `UNKNOWN_MODULE` / `OWNER_UNCONFIRMED` / `OWNER_CONTRACT_MISMATCH`; active and synthetic state hashes unchanged. |
| Owner A delta contains B's file, or two owners claim one path | Reject `CROSS_OWNER_PATH` / `DUPLICATE_OWNER`; no priority-order or wildcard resolution silently chooses an owner. |
| Shared app/router/contract/config touched by a sole module | Reject `SHARED_PATH_REQUIRES_INTEGRATION`; a fabricated caller-supplied approval cannot bypass the trusted active contract. |
| Two route records have the same method and path; prefix heuristics assign all research routes to one module | Reject ambiguous records; correctly allow distinct exact routes under the shared prefix when ownership is explicitly proven. |
| Stale route contract | Detect runtime-B `/workspace/us-mapping/refresh` and `/workspace/daily-cycle` POST routes absent from the candidate service-role route list. This is concrete evidence that the old route list cannot stand in for the current business registry. |
| Frontend delta adds, removes, renames or changes an unlisted generated file, HTML reference or shared chunk | Reject `STATIC_OUTPUT_UNOWNED` / `STATIC_GRAPH_MISMATCH`; verify complete dist inventory, including deletions and preserved referenced assets. No entire-dist copy/rollback. |
| Symlink ancestor/file, `..`, absolute path, duplicate normalized path, filesystem case/Unicode alias | Reject before writes. Include Mac-relevant alias fixtures without claiming actual Mac filesystem verification. |
| API-only A/B sequential releases and A rollback | Final app contains A+B; rollback changes only A's exact reverse delta while B, contracts/config, every static byte and synthetic state remain identical. |
| Later B depends on shared version introduced with A | A rollback rejects if it would remove/change required shared bytes or interface compatibility cannot be proven. |
| Same-base concurrent candidate with stale ownership generation/base/static identity | Existing lock/CAS rejects the second candidate; no silent rebase. Rebuild from the new active identity. |

## What remains CANNOT_CONFIRM

Approved business owner IDs, complete dependency closure, all route registrations (the nested WeChat router is absent), live active release/manifest/inventory/generation, actual dist/build identity and generated dependency graph, external state authority and schema compatibility, and the live publisher/launcher/readback chain. Runtime-B source is evidence of code composition, not evidence of a current active deployment. The two additional manager POST routes above demonstrate source drift relative to the candidate service-role contract. No current Mac behavior, UI/API behavior, natural-language business behavior, deployment or service continuity is asserted.
