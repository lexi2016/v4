# V4 six UI/API fixes and PDF night admission

Source-only change capsule for lexi2016/v4, branch codex/v4-ui-six-fixes-20261027. Apply the API component over the exact actual API baseline runtime-graph-repair-20261026-api-r2, and the Main component over the exact Main baseline runtime-graph-repair-20261026-main-r2 or its preserving lifecycle successor. Every before/after source hash is pinned in evidence/COMBINED_SOURCE_FREEZE.json. This capsule is not a standalone application and the mixed worktree must not be deployed.

The six fixes cover current display names, pagination wording, HK-only missing receipts, independent US-ledger status, verified PDF-card status, and manager generated_at. PDF queue admission uses Asia/Shanghai 02:00 inclusive to 08:30 exclusive; daytime collection continues to enqueue and existing in-flight processing may finish.

Independent Sol source/test review passed after preserved Luna failures and frontend baseline correction. Name evidence covered 90/90 identities; 32 backend cases, 13 PDF-window cases and 19 frontend cases passed. Full TypeScript checking retains 30 unchanged actual-baseline errors. Runtime deployment, API/UI acceptance and the first natural 02:00 cycle are separate receipts.

Raw market/research data, PDF bytes, source responses, runtime directories, dist, logs, credentials and environment files are excluded. Rebuild frontend assets with the pinned actual frontend baseline; source-review hashes bind the two generated overlay files but their bytes are deliberately not uploaded here. All research/trading safety flags remain unchanged.

The unchanged actual frontend source baseline is also archived under components/api/apps/web, so future rebuilds preserve the active UI rather than the superseded canonical tree. Dependency manifests are under dependencies/apps/web. The raw owner-observation test fixture remains local and is represented only by its SHA in evidence/FRONTEND_SOURCE_PROVENANCE.json. These baseline copies add no behavior changes and reuse the independent source-parity evidence.
