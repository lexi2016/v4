# Manager plan date gate: RED candidate

Base: `27c7d08c4e2d5261ff84a74db03daa033dce5759`.

This increment contains seven tests and unchanged, SHA-pinned original owner
sources. It does not implement the V5 manager adapter or ordinary API route.
The original full `get_workspace` / `refresh_workspace_plan` / `_read_plan` /
`verified_plan_attempt` execute against a temporary store, without importing
`ManagerResearchJobService` or starting its worker pool.

## Independent Mac command

In a fresh checkout of this candidate, use the existing Mac Python environment:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 V5/tests/test_manager_plan_date_gate.py -v
```

No request JSON or production input root is required. Fixtures are synthetic,
explicitly labelled, saved through the original store and read by the original
US mapping reader. They are not actual recovery or PIT evidence. Source files
are assembled into a temporary directory and checked against the manifest;
existing V5 capsules remain unchanged. Run this file in its own process.

Expected behavioral RED: `test_completed_previous_session_is_not_admitted_at_current_cutoff`,
`test_valid_empty_does_not_bypass_session_gate`,
`test_actual_workspace_keeps_recovery_separate_and_get_has_no_writes`, and
`test_actual_saved_plan_independent_store_same_attempt_rejects_old_session`
and `test_rejected_daily_artifact_does_not_change_valid_plan_input_identity`
reach an assertion showing the original owner incorrectly consumes US07 at a
cutoff whose calendar expects US08. Import/setup errors do NOT verify RED.
The late recovery rejection and wrong-run terminal attempt tests are controls.

Cloud validation: Python AST syntax and source digest inspection only; no
product test execution. All Mac outcomes are NOT_RUN pending independent logs.

## Source choice and next gate

`tests/fixtures/manager_owner/manifest.json` gives each effective relative path,
original commit/path and SHA. Issue29 workspace/history override R2; R2
workspace_plan/daily_channels/connect files override older copies. Remaining
sources reuse frozen V5 capsules or explicit canonical original files.
This is a test fixture closure, not a production capsule or full-service import.

Ruling: the user explicitly assigns all product testing to the existing Mac task;
RED/GREEN execution is delegated there, overriding the skill's local test loop.
No implementation before confirmed behavioral RED. Cost: fixture import issues
must be corrected from Mac traces rather than cloud execution.

Next: retain the same behavioral assertions against the V5 original-owner
adapter; bind current US source/session identity without equality between daily
and plan cutoffs or daily and workspace input identities; preserve timestamp
precision and nullable evidence. Complete ordinary API read-only wiring after
owner persistence and same-run readback. The seven tests alone do not claim the
announcement/oversold/US-to-API chain is complete.
