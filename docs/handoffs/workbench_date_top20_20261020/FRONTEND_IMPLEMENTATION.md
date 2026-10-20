# Frontend candidate preparation

**State: PREPARED_NOT_DEPLOYED.** The date dropdown and previously accepted candidate-count label are prepared as a frontend candidate. The active r8 release was not modified; no business-state API call, service change, scheduler change, deployment, or activation was performed.

The machine receipt is [FRONTEND_DELTA.json](FRONTEND_DELTA.json), SHA-256 b789fac96ac28754d9c600d930ecf0d930360c7e5977712e37e032a51e040f50. The prepared-state receipt is [FRONTEND_PREPARED.json](FRONTEND_PREPARED.json), SHA-256 1fa62966c23663e99331ef9f7a150d23aebcc89a63024920d7eab1db00d54fc9. The prior metadata FAIL and its exact cause are retained in [FRONTEND_METADATA_CHANGELOG.json](FRONTEND_METADATA_CHANGELOG.json), SHA-256 b9f69bc6f66ac62626b457e97331267e28caca7d6c0c3b6e4c58f1d7e30b05b0.

## Distinct source identities

The task worktree is /Users/lexi/.codex/worktrees/workbench-date-top20/v4_app, branch codex/workbench-date-top20-20261020, frozen base 9b19ca180138499e5e29501fbf07cb03f61b5fd7. Its before hashes come from read-only exact-path lookup at the base revision; its after hashes in the receipt are computed from that worktree.

The successful Vite build used the complete actual-r8 source clone at /Users/lexi/.codex/worktrees/workbench-date-top20/v4_app/docs/handoffs/workbench_date_top20_20261020/local_only/frontend_candidate/apps/web. The source overlay patch targets the actual r8 app root /Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-daily-workflow-20261020-r8/app. These are separate from the task worktree. In particular, the worktree api.ts and types.ts do not byte-match the r8 candidate because the task branch lacks r8-only announcement API methods and types. The useWorkbench.ts difference is specifically that the task worktree retains `if (!dateInput.value) return` in changeDate, while the r8 overlay keeps the original changeDate without that line; the r8 selectDate entry validates with isValidDate before calling changeDate. The r8_source_overlay.changed_files hashes are the actual-r8 preimages and candidate-source postimages; do not substitute task-worktree hashes.

The overlay patch is [FRONTEND_SOURCE_OVERLAY.patch](FRONTEND_SOURCE_OVERLAY.patch), SHA-256 56639d36eed894a7663ee098e92d98fa3dc1f8f1a04672e9eb14e7f6f063e950. Its seven source/test paths passed the recorded patch dry-run against the actual r8 app root. The build output is under local_only/frontend_candidate/build_output/dist; the minimal static closure is under local_only/frontend_delta and consists of the manager-selection HTML replacement and the two new manager-selection JS/CSS assets. Apply those three paths only, preserving all prior assets.

The date control is a single dropdown loaded lazily from read-only GET /api/v1/runs/date-list. It validates, deduplicates and sorts saved dates, includes the current target, displays YYYY-MM-DD, preserves compact YYYYMMDD route/API values, and clears prior phase/run/paging when changed. The transplanted usMappingCandidateCountLabel reports the number of research candidate rows when the catalog is available and unknown when it is absent. Candidate rows remain fully rendered without filtering or truncation.

## Existing verification

The independent component review passed 4/4 focused tests and confirmed all 10 rebuilt static output files were byte-identical to the recorded candidate output; the r8 source baseline and overlay typecheck diagnostics had matching SHA. This metadata correction changes no source, tests, patch, or static build bytes, so component evidence is reused; an incremental review is needed for the corrected metadata. No tests or build were rerun for this metadata-only correction.

The original focused command was npm test -- --run src/manager-workbench/__tests__/workbench_calendar.spec.ts src/manager-workbench/__tests__/workbench_dates.spec.ts (4/4 passed). npm run build passed (Vite 7.3.6, 100 modules). npm run typecheck exited 2 with diagnostics only in unchanged files; no changed workbench file was named. npm ci completed earlier with 8 audit advisories (2 moderate, 6 high) and npm policy denied esbuild/fsevents install scripts.

Git synchronization is owned by the controller and was not run by this writer. The intended sync scope is the minimal task-worktree source delta, two focused tests, the r8 overlay patch, and compact receipts; exclude the local candidate clone/build output, node_modules, and runtime release contents.

CANNOT_CONFIRM: activated API readback, rendered runtime UI, natural-period behavior, and the separate HK Top20 research comparison. Deployment/activation and Git synchronization remain unrun. This component receipt does not prove selection performance or close the overall research goal.
