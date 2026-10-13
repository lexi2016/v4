# Integration candidate · 2026-10-13

Status: IMPLEMENTED_FOR_REVIEW. No deployment, launchd change, official state write, new collection owner activation, or browser acceptance has occurred.

The canonical app and daemon patches are distinct from the live R10 API and R8 scheduler patches. Use `deployment-deltas/api-active-candidate/apps/api/v35_api/app.py` and the matching active patch for the API; do not replace R10 with the canonical app. The candidate builder uses the existing `ops/api_release_integration.py`, binds the active plist/manifest/inventory, and aborts on drift. It carries only the manager page's built asset dependency closure; unrelated active pages and assets remain unchanged.

The new API attaches saved-only GET and asynchronous POST under `/api/v4/manager-workbench/`; the existing `/manager-selection/` URL mounts the new Vue component. The actual active-base factory test verifies 251 selected synthetic rows, 51 rows on the final page, immutable readback, and no old manager business modules loaded.

The scheduler selects the new in-process manager hook when the operator supplies `V4_MANAGER_WORKBENCH_CONFIG_PATH`. A configured invalid/revoked new binding fails closed and does not resume the old hook. The new job threads are independent of the old 50-second subprocess limit. Capture remains disabled. When no new binding is configured, the explicitly preserved old hook branch supports whole-module rollback; the new owner and old owner are never initialized together.

Per-job source references are resolved from the existing owners using calendar dates, exact sessions, run/manifest identities, availability cutoff and raw SHA. Monthly membership verifies all six raw references while keeping the producer's canonical capture identity separate from its raw file SHA. Stage snapshots use frozen exact-day HK entries. A later or wrong-day source is not substituted for a missing required date. Missing source, ambiguous units and missing original US priority metadata remain UNASSESSED/CANNOT_CONFIRM. No full close ranking owner has been confirmed. Current-day announcement acquisition remains a gap because exclusive collection has not been activated.

## Temporary saved readback

The coordinator may explicitly start the foreground local helper, inspect it, and stop it afterward. It binds only 127.0.0.1, refuses existing production ports, blocks POST, runs no scheduler, and makes no new model calls. State is confined to the already isolated canary or synthetic directory. `serve_isolated_candidate.py --case real --port 18873` displays the immutable r2 RETROSPECTIVE 20261012 result; `--case synthetic` displays the independently generated 251-row 20261013 result. Use the exact command/URLs in `integration-implementation-receipt.json`. The page for 20261014 has no saved job and exercises the missing/empty state. These two materials must remain clearly separated.

The real single article is an administrative proxy form. Reader and independent Reviewer shared the same frozen input SHA and used different execution identities. Their role material hashes differ because Reviewer material contains Reader output. The announcement lane is NOT_SELECTED; the saved aggregate is UNASSESSED because the other lanes were not run. It is not a positive selection or historical PIT proof.

## Activation and rollback plan (not executed)

Before any separately authorized activation, reread the current API plist/manifest/inventory and scheduler identity and rebase if they differ. Assemble the API increment through the existing publication mechanism and shared lock. Build the scheduler increment from R8's actual base using only its manager-hook patch plus the new module closure. Bind both services to the same reviewed operator config and isolated/new manager state root. Remove the old exclusive manager collection binding from the active manager ownership path when selecting the new hook; collection remains off until separately accepted. Preserve every other scheduler workload and the parallel Stage release.

Rollback restores the previous API release/plist and scheduler release/binding as one manager ownership transition, removes the new hook selection, and restores the old manager page assets from the old release. Keep the new immutable state for investigation; never copy new snapshots into old manager history. Do not run old and new collection owners together. This plan does not authorize any service or state change.

## Synchronization exclusions

Upload only necessary source, tests, metadata receipts and small generators. Exclude node_modules, all `.tmp`, generated `backend-http.json`, compiled dist, `api-delta-source`, isolated API candidates, raw real materials, model body/output files and historical business artifacts. Preserve the prior failure receipt and its output hashes. The fixed 7-file executor/private-schema receipt has independent PASS and is reused without modification.
