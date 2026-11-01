# Canonical manager repair source-delivery handoff

Status: `IMPLEMENTED`; writer-focused checks `PASS_SCOPED`; independent integration review is pending. This is a source delivery into the sole V4 checkout, not a release or runtime deployment.

The canonical changes forward-port the reviewed request-day HK observation reader/display isolation, same-target rebound history selection, and compact UI rendering. The manual HK securities observation stays display-only; planner context remains the prior session, and selection/BUY state is unaffected.

## Changed source and tests

- `apps/api/v35_api/manager_workbench_router.py`
- `v4/manager_research/workspace.py`
- `v4/manager_research/workspace_projection.py`
- `v4/manager_research/workspace_plan.py`
- `apps/web/src/manager-selection/catalystObservationPanel.ts`
- `apps/web/src/manager-selection/catalystObservationPanel.runtime.spec.ts`
- `tests/test_manager_current_observation.py` (new; six isolated tests)
- `tests/test_manager_workspace_targeted_r2.py` (eight focused selector tests and fixture metadata)
- `tests/fixtures/manager_current_observation_20261002/` (four byte-copied test inputs and their binding)

`SOURCE_HASHES.json` binds each final SHA and its preimage SHA where one existed. `CANONICAL_SOURCE_DELTA.diff` contains the exact source/test edits; its header directs the four copied fixture payloads to the hash binding. The seven original allowed files were snapshotted before changes under `preimage/` and listed in `PREIMAGE_BINDING.json`.

## Existing canonical differences preserved

The canonical `workspace_plan.py` preimage had extra owner-consumed daily-supplement logic absent from the candidate branch. The forward-port replaces only `_read_hk02_panel_witness` with the reviewed selector and changes the `read_rebound_screen` preamble through its existing `master_names` binding to pass the native `previous5_session_dates[-1]`. The pre-existing `_read_hk02_daily_supplement_witness`, later supplement and screen body, and all other bytes were verified byte-identical to the preimage. The canonical selector test retains its existing retrospective `&view=dynamic` request; candidate-only changes outside the reviewed selector tests were not copied.

The three current-observation backend sources and the UI renderer had preimage hashes matching their reviewed release baseline, so their reviewed files were ported byte-for-byte. The runtime spec and Python observation test only changed their fixture path to this checkout. The new fixture files are byte-for-byte copies of the independently hash-bound read-only capture test inputs; they establish no new authority or producer.

## Reproduction and verification

`PRE_FIX_REPRODUCTION.json` captures the red behavior before source changes: six current-observation tests failed and eight selector tests failed while five legacy selector tests passed. Final commands and full logs are in `TEST_RECEIPT.json` and `logs/`.

- Current-observation tests: `6 passed`.
- Rebound selector slice: `13 passed, 40 deselected`.
- Frontend runtime spec: `11 passed`.
- `py_compile` for all four backend modules and both Python tests: passed.

The three input candidate changes were independently reviewed before this port: `PASS_SCOPED` for observation R2, `PASS_SCOPED_REBOUND_OWNER_SELECTION_R2`, and `PASS_SCOPED` for the compact UI files. Exact review receipt paths and hashes are in `SOURCE_HASHES.json`. The canonical forward-port itself has not yet received an independent reviewer verdict.

## Evidence limits

`TESTED` here means only the writer's isolated focused runs; formal `TESTED`/`REVIEWED` remain pending the separate reviewer. No API or browser UI verification, service reload, deployment, or natural slot is claimed. Those layers remain `CANNOT_CONFIRM`. The change does not modify A-share behavior, Stage/BUY gates, production permissions, source data, or running services.
