# US mapping deployment preflight receipt

State: READ_ONLY_PREFLIGHT_COMPLETE; no candidate prepared, no business POST, no service switch. User authorization to deploy already exists; the controller asked for scope review before preparation or switching.

## Live identity and retained state

- com.lexi.v35.api-only is PID 4473, listening on 127.0.0.1:8873. Its working directory is the active release announcement-fixed-membership-20261019-r1/app; the active release manifest SHA-256 is 0d4ae8d528c337befd9bcb8b51ef8847a81010702866c3e4b36f8b7e9531083e.
- The launchd plist SHA-256 is efa716de4a6e75d75afda72aecbb8943782eef361254f22a1195903584b999f9. The active app inventory contains 1262 files, aggregate SHA-256 d7a0a56160f80ea35ba490f8a5b724305c3e5ed47712a25ce31fea26741f02c1.
- GET /healthz returned HTTP 200 and status=ok; GET /readyz reported production_allowed=false, buy_gate_updated=false, orders_sent=false. A bounded 30-second retry of GET /api/v1/runs/date-list?date=20261020 returned HTTP 200 and the expected date/release identity; the response's process_status remains CANNOT_CONFIRM.
- The scheduler (com.lexi.v35.scheduler, PID 75648), Vibe (com.lexi.vibe-astock.local, PID 1102, port 8910), and stage-center scheduler identities were read only. No service or scheduled task was changed.
- GET /api/v4/manager-workbench/history?date=20261020 returned 12 versions. Current default is NEXT_DAY run c01031c0470f4908986390c4dcf8be01; existing MANUAL run 571e25ceffed46528fbc6b8ea45de3d3 remains listed. Both run IDs and product/input hashes are frozen in SCOPE.json and must be retained.

## Planned single run and inputs

After controller confirmation, the only planned business request is one POST /api/v4/manager-workbench/runs with {"target_date":"20261020","phase":"MANUAL","lanes":["US_MAPPING"]}. It uses the existing US session 20261016 and saved owner inputs. No POST or material re-run occurred during this preflight.

The active config is us-industry-observed-api-20261018-r1.json (SHA-256 75c1efbd5a092b7945fc5baed98c64b37a7165ccf7eafc6abb9c1d540917c5db). The full mapping catalog, review overlay, and recovery overlay are read from the active release with the hashes recorded in SCOPE.json; recovery identities are R924→06808/WMT, R955→09633/KO, R942→06993/PG. The saved quote owner artifact is partial (490/547 symbols, 57 gaps) but includes WMT, KO, PG with valid positive finite prices and arithmetic checks. Its artifact, receipt, owner manifest, and expected scope hashes are recorded in the scope. No raw quote payload is copied here.

The six intended source changes and active-release preimage hashes are recorded in SCOPE.json. api.ts, useWorkbench.ts, and types.ts match the active release and are not deployment deltas. The static plan rebuilds from active source with only the two manager-workbench frontend patches in an isolated temporary directory; it will replace only the manager-selection entry and its new hashed assets. The root entry, daily-research-command entry, and all 26 existing assets must remain byte-identical. The local apps/web/dist is a validation artifact and is not a deployment input.

## Release and rollback readiness

The active release's ops/api_release_integration.py supports explicit deltas, but calling module_role_contract() fails because deployment/api_module_contracts.json is missing from that release. The generic ops/build_release_candidate.py copies the full tracked source tree and full web build, which exceeds the frozen allowlist. Existing runtime prepare/activate scripts are bound to older release and candidate IDs. No task-specific candidate exists. These paths are not safe to run for this task.

The prior release, manifest, API plist, and historical run IDs remain untouched and provide the rollback preimage. The exact activation/rollback command remains CANNOT_CONFIRM until the controller chooses a compatible existing release path. Do not adapt or run a stale helper. Once a compliant preparation path is approved, preserve a byte-identical plist copy before any switch; if API/UI review fails, restore that plist and restart only com.lexi.v35.api-only, then verify its PID/cwd, health/readiness, and retained history.

The UI Reviewer must use /manager-selection/?date=20261020&run_id=<new_run_id> and verify the returned snapshot.run_id matches the newly generated MANUAL run. The default page currently selects old NEXT_DAY run c01031c0470f4908986390c4dcf8be01; it is not valid evidence for this run.

## Checks and result

- Worktree: branch codex/us-mapping-e2e-repair-20261019, HEAD 552c11aa58645a33078a5f67abed4a293ab71df0; tracked tree clean. Existing generated untracked .venv, apps/web/node_modules, apps/web/dist, __pycache__, and prior local_only evidence were preserved.
- Read-only checks: git status --short; git rev-parse HEAD; git branch --show-current; shasum -a 256 on source scope/receipt; lsof/launchctl/plist readback for listener and service identity; GET /healthz, /readyz, /api/v1/runs/date-list?date=20261020, and /api/v4/manager-workbench/history?date=20261020; targeted rg inspection of active overlay references and existing release helpers.
- Release readiness check: import active ops/api_release_integration.py and call module_role_contract(); result FileNotFoundError for missing deployment/api_module_contracts.json (blocking; no candidate was built).
- Tests: NOT_RUN in this preflight phase. The prior source implementation receipt contains the accepted focused tests; the parent said not to rerun them for this phase.
- Not performed: UI automation, actual API candidate readback, new run, service switch, rollback exercise, commit, push, or deploy.

## Exact files changed in this phase

- docs/handoffs/us_mapping_e2e_repair_20261019/deployment/SCOPE.json
- docs/handoffs/us_mapping_e2e_repair_20261019/deployment/PREFLIGHT_RECEIPT.md
