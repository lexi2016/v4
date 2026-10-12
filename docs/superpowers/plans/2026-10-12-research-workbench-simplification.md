# V4 research workbench simplification plan

Status: approved four-batch plan; execute serially with one Writer per batch and a separate read-only Reviewer before integration.

## Frozen target and baselines

Unify the hourly research implementation used by the API and scheduler candidates while preserving their public facades, source provenance, immutable artifacts, UI behavior, and all unrelated manager, selection, and overlay methods. The sole source worktree is `/Users/lexi/.codex/worktrees/research-workbench-simplification/v4_app`, seeded from canonical source commit `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`. The current-source baseline and runtime module SHAs are recorded in the controller's `baseline.json`.

Runtime comparison is bound to matching input identity. At the start of this plan, the API had naturally advanced to `20261012/2300`, payload SHA `9fa6d40f37c52f79d9cdc1626498320cb4089d231e5a2598cb76234f459cc099`, with 19 declared gaps; the browser still displayed the `2200` page. The day API uses `archive_date` and returned `8/8 READY_WITH_DECLARED_GAPS`. These are read-only comparison anchors. Do not pin latest to `2200`, rewrite a natural artifact, or compare outputs from different source SHAs.

## Preserved boundaries

- Preserve every non-hourly method's source bytes in shared store facades, including manager, selection, and overlay methods. Keep runtime-specific hourly extensions behind their existing facade when they are not common.
- Keep A/HK date and pool boundaries, source SHA, manifest, run ID, PIT checks, read-only research status, and `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false` unchanged.
- Do not add a producer, fetch a second copy of existing evidence, write business inputs/artifacts/receipts/latest, alter active releases, or touch Vibe 8910, services, or schedules.
- Use isolated fixtures and candidates for tests. API, page, deployment, and natural-period claims require their own later readback evidence.

## Serial batches

| Batch | Owned change | Acceptance evidence |
| --- | --- | --- |
| 1. Shared version and dependency identity | Extract one shared hourly store implementation with compatible entrypoints. Publish a deterministic path/SHA bundle for common modules and include that bundle plus relevant runtime dependency bytes in transformer identity. Keep existing archive and receipt immutable on equivalent output; reject conflicting output. | Focused hourly runner and ready-empty tests; candidate API and scheduler bundles have identical common paths and SHAs; runtime-specific adapter SHAs and preserved methods are recorded. Independent Reviewer must inspect the exact diff and rerun the focused tests. No release action in this batch. |
| 2. Exact evidence read and time validation | Move status/run evidence reads to one common evidence reader; make time validation pure; remove the reverse collector-to-store bridge and the temporary hourly bridge. | Offline exact-source tests cover source SHA, receipt/run/path identity, slot/date/cutoff, missing/tampered/cross-run evidence, and rejection cases. The same frozen input SHA is used in all comparisons. |
| 3. Page contract and status | Keep unassessed distinct from a verified effective zero; preserve declared gaps and source provenance through API and page projections. | API and UI tests prove missing/unassessed, verified zero, and populated states remain distinct and date-bound. Reloaded API/page evidence is reported separately from test results. |
| 4. Confirmed dead code and integration | Remove only code proven unreachable after the first three batches and integrate the reviewed common implementation. | Reference search and scoped regression tests pass. Record candidate SHAs, release identity, API `archive_date` readback, reloaded page state, and natural-slot evidence independently. Do not call a layer complete without its receipt. |

## Review, release, and readback

Each batch stops at a candidate handoff until a different-identity Reviewer records `REVIEWED` and `BEHAVIOR_VERIFIED` for that frozen scope. Writer test results are supporting evidence only. Controller-owned integration, release, and browser readback remain separate states; this plan does not authorize deployment, push, service or schedule changes, or writes to runtime data. If a required runtime action is later authorized, record the exact candidate SHA and dependencies before release, then read the API using `archive_date`, reload the existing 8873 page, and wait for a natural slot before making natural-run claims. Keep any layer without direct evidence at `CANNOT_CONFIRM`.

## Stop rule

Stop the current batch on behavior drift, wider date/PIT scope, data loss, hidden evidence gaps, historical writes, or any non-target method change. Preserve the reproducer, before snapshot, diff, and hashes; do not mask the issue with a fallback or broader rewrite.
