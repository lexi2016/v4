# R2 independent review

**Decision: PASS for the frozen candidate’s requested continuation contracts and the bounded manager-research parent-SFC integration.** The final API, selected history, and Vue tests passed against the frozen candidate. This does not establish a deployed-browser result, a real Mac run, a naturally scheduled run, or an October 8 live-data result.

## Frozen source reviewed

I verified the source hashes locally against the freeze notice before testing. The “before” hashes are from the read-only R1 worktree.

| File | R1 before SHA-256 | Frozen R2 after SHA-256 | Reviewed delta |
|---|---|---|---|
| `v4/manager_research/workspace.py` | `58a471c5ce7ece837c66948392ec2e6d73459343515225e19d694749c45ab1a4` | `a6225ef5583a73c066a5c31400f84e237aaceb63abefcf199cfb8c9b8af7dcdc` | Exact saved date bindings now permit the sealed plan context for `auto` as well as `dynamic`. The past-date `auto` early return to history remains before that branch; source owners are still re-read and the usual identity comparison still decides whether the saved plan is current. A nearby comment was broadened from “dynamic” to “non-history.” |
| `apps/web/src/manager-selection/catalystObservationPanel.ts` | `516b20050a9c4911415f8d5d9b94e5f58aa74c6b01711ec728edbe7582b351c6` | `ffd5c8cbfdaba9eb7e277695114647ef037b88ae16269be5547d3eff0649d3a3` | The explicit plan refresh now sends `selection_date: selectionDate`, fixing the undefined shorthand value while retaining `announcement_date: publicationDate`. |

I made no production or Writer-test edits. The independent API test is in `reviewer/test_workspace_auto_readback_contract.py` (SHA-256 `e20677a6aef3d1ea856b8692cb9beb303c921473b95839d81248de50de6d3c29`). The full-parent UI spec SHA-256 is `2d1f353823a96745f4d1c4a0e9eed55f9ba1caec0ea766bd0f16861e303dc668`; its route worker SHA-256 is `bc40e4716f5dffad231318723e130a6879518a5ec681d4a31df316014d265eaa`.

## Verification results

| Check | Result | Log |
|---|---|---|
| Independent real-route API and owner-contract regression | **PASS — 4 passed, exit 0** | `independent_api_regression_final.log` |
| Selected past-auto/history contract checks | **PASS — 2 passed, exit 0** | `selected_history_regression.log` |
| Original `ManagerSelectionView.vue` parent-SFC manager-research integration | **PASS — 5 passed, exit 0** | `full_parent_sfc_daily_integration.log` |
| Full `npm run build` and full-app browser/deployment test | **NOT RUN** | The source-closure record still lacks the original two HTML entry files; no build/deployment claim is made. |
| Whole-app typecheck | **NOT RUN** | The original `issue8R2.ownerObservations.json` input remains unavailable; I did not create a stub. |
| Live Mac/API, real business data, natural scheduling, or production deployment | **NOT RUN** | Outside this isolated review boundary. |

### Independent API/owner regression

Command (exit 0; Python 3.14.6 / pytest 9.1.1):

```bash
set -o pipefail
V4_TEST_SOURCE_ROOT=/workspace/scratch/a154a3323e32/investigation/continuation_20261009/candidate \
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/workspace/scratch/a154a3323e32/investigation/continuation_20261009/candidate:/workspace/scratch/a154a3323e32/investigation/continuation_20261009/candidate/tests \
/workspace/scratch/a154a3323e32/test_env/bin/python -m pytest -p no:cacheprovider -vv \
/workspace/scratch/a154a3323e32/investigation/continuation_20261009/reviewer/test_workspace_auto_readback_contract.py 2>&1 \
| tee /workspace/scratch/a154a3323e32/investigation/continuation_20261009/reviewer/independent_api_regression_final.log
```

The test requires the explicit `V4_TEST_SOURCE_ROOT` and rejects a missing or invalid source root before importing candidate modules. It uses the actual FastAPI `TestClient` routes, original service/store, owner readers, and the US market adapter/bridge. Synthetic market and research fixtures are written only beneath pytest temporary directories.

The four cases verified:

1. A route `POST` followed seconds later by a `GET` omitting `view`, `selection_date`, and `announcement_date` returns the same-day plan as `CURRENT`/`VERIFIED`. Its readback `read_at` and `last_checked_at` match the later GET clock, while its sealed research cutoff stays at POST time. The two individual mismatched bindings (selection and publication) use the later evaluation cutoff and return `STALE_INPUTS_CHANGED`; they do not borrow the saved cutoff. A direct `include_saved=False` owner read also uses its actual later cutoff and has no `plan_product` readback field.
2. A future target’s evening plan is read back by ordinary `auto` GET with the exact same run and saved cutoff while the read timestamp advances.
3. A valid synthetic US-owner source replacement is published through `ResearchPeripheralStore.replace`; the original reader/adapter replays the changed verified payload, and the old plan remains stale.
4. A later synthetic US daily cycle is persisted by the original mapping owner with an explicit scheduled `LATE_CATCHUP` dispatch receipt and `natural_run_verified=false`. The old saved plan remains current under its original run and cutoff; its actual GET read time advances; the owner-chain reference reports `NOT_CONSUMED_AFTER_CUTOFF` for the later cycle; and the overlay reports `latest_attempt_after_plan_cutoff=true` / `latest_attempt_affects_saved_plan=false`.

The final API run emitted one Starlette/httpx deprecation warning; it exited 0. Two earlier reviewer-harness runs exited 1 because my initial assertions expected `plan_product` on `include_saved=False` and attempt-overlay fields when no dispatch receipt existed. Those assertions were corrected to the owner’s actual return contract; the corrected final run passed. The iteration logs are retained as `independent_api_regression.log` and `independent_api_regression_fixed.log` for audit and are not candidate failures.

### Historical behavior

Command (exit 0; 2 passed):

```bash
set -o pipefail
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/workspace/scratch/a154a3323e32/investigation/continuation_20261009/candidate:/workspace/scratch/a154a3323e32/investigation/continuation_20261009/candidate/tests \
/workspace/scratch/a154a3323e32/test_env/bin/python -m pytest -p no:cacheprovider -vv \
/workspace/scratch/a154a3323e32/investigation/continuation_20261009/candidate/tests/test_manager_history_readback_r1.py::test_history_missing_does_not_scan_live_owners \
/workspace/scratch/a154a3323e32/investigation/continuation_20261009/candidate/tests/test_manager_history_readback_r1.py::test_auto_history_and_explicit_dynamic_are_distinct 2>&1 \
| tee /workspace/scratch/a154a3323e32/investigation/continuation_20261009/reviewer/selected_history_regression.log
```

This is the narrow R1 history boundary, not a repeat of the R1 suite. The parent-SFC test additionally exercises a past-date `auto` read with no qualified saved plan (`NOT_MATERIALIZED`) and then an explicit `dynamic` read that is labeled as including later information.

### Parent-SFC test

Command (exit 0; Vitest 4.1.10; 1 file, 5 tests passed):

```bash
cd /workspace/scratch/a154a3323e32/investigation/continuation_20261009/candidate/apps/web
set -o pipefail
V4_TEST_SOURCE_ROOT=/workspace/scratch/a154a3323e32/investigation/continuation_20261009/candidate \
V4_TEST_PYTHON=/workspace/scratch/a154a3323e32/test_env/bin/python \
/opt/codex/runtimes/codex-primary-runtime/dependencies/node/bin/npm test -- --run src/views/ManagerSelectionView.dailyIntegration.spec.ts 2>&1 \
| tee /workspace/scratch/a154a3323e32/investigation/continuation_20261009/reviewer/full_parent_sfc_daily_integration.log
```

The test mounted the original `ManagerSelectionView.vue` SFC and bridged its manager-research HTTP requests to the original FastAPI `TestClient` worker. It passed checks for same-date `auto` readback, explicit three-date plan POST followed by same-run `auto` GET, missing-US-input receipt with announcement output preserved and unknown counts kept unknown, delayed old-date response handling after changing target date, and separation between past-date `auto` history and explicit later `dynamic` view.

The date-race case gates the old 20261008 GET response until after the user changes the plan date to 20261009. It waits for the old response’s JSON parser signal and a subsequent event-loop turn before checking the DOM, then verifies the new target’s `auto` read has completed and the old announcement text did not overwrite the current panel. The generation/readback case separately checks the POST and GET bindings and the same verified run in route responses and the freshly queried current DOM.

This is an SFC DOM integration for the manager-research region. Unrelated manager-page endpoints return an explicit 404 in this fixture, so the other page sections are not claimed green. It is not a deployed browser test. For this run I temporarily symlinked the candidate’s web `node_modules` to the fixed existing dependency directory at `/workspace/scratch/a154a3323e32/candidate/apps/web/node_modules`; after the test, I removed that symlink. The npm output had an unrelated `http-proxy` config warning and exited 0.

## Boundary

All test-generated research, market inputs, state stores, and dispatch receipts were synthetic and isolated. The R2 behavior is supported by these frozen-source API and DOM tests only. No test in this review proves that a natural October 8 run occurred, that a real Mac or live API was exercised, or that any production deployment was made.
