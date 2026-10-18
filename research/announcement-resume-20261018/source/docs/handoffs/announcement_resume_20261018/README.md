# Announcement Flash frozen-batch resume

This handoff adds an explicit resume action for an interrupted announcement run. Resume consumes the original saved capture product and input, and binds the child job to the source input, progress, and queue-state SHA-256 values. It does not capture new announcements or change the Flash prompt, model, validator, membership gate, or BUY behavior.

The read-only `GET /api/v4/manager-workbench/announcement-flash` response exposes `data.resume` only for the current latest target-date run. `INITIAL_CANARY` is eligible only when the interrupted source has no result, exactly one planned orphan has no saved validated result, the model owner is gone, and at least one pending part is present. The snapshot reports `recoverable_orphan_count`; the UI shows that count and `max_model_calls: 1`. A dry-run leaves the orphan `RUNNING`, reports it as `OWNER_CLEAR_NO_RESULT`, and does not name it as a canary. During an explicitly submitted resume, the worker rechecks the owner and saved result, records the interrupted attempt, binds a recovery identity to the source job and hashes, then admits at most one request. If ordinary pending work is blocked by unverified historical success, that recovered orphan is the canary. After a successful saved canary result, a later GET may expose `CONTINUE_AFTER_CANARY`; the user must explicitly click again to submit remaining eligible pending work.

The resume path preserves already-succeeded queue parts and their validated artifacts. Failed parts stay terminal and are not retried. Historical part results use the top-level `v4.manager_workbench.announcement_chunk_part_result.v1` envelope; the runner verifies the saved input SHA, validated-result SHA, envelope fields, part descriptor, and source-unit-map binding against the historical queue identity. A current pending part that matches a verified historical success by article, body, source-unit map, and part contents remains `CANNOT_CONFIRM` when source or chunk-plan provenance differs. It is counted as history-blocked and kept out of the model queue; the old answer is never reused. A complete or unreadable saved result for the orphan is also kept out of the model queue. The orphan is recoverable only after the existing queue confirms the exact frozen part, no model lock owner is active, and no complete saved result exists. An ordinary zero-attempt pending part is selected before an orphan recovery only when it is independently eligible.

Repeated POSTs with the same source job and three source hashes return the same submitted job. The generic `/runs/{id}/retry` route rejects announcement capture operations with `ANNOUNCEMENT_FLASH_RESUME_REQUIRED`; users must use the dedicated resume action. The activation/rollback procedure for the V4 API also requires the all-date submission lock in [the Futu board cutover runbook](../futu_board_completion_20261018/ACTIVATION_ROLLBACK_RUNBOOK.md).

## Read-only dry-run

`ops/run_manager_flash_announcements.py --resume-dry-run --resume-frozen-batch` validates the exact source artifacts and exercises queue planning with admission and model dispatch disabled. It reports the frozen per-part status counts, pending eligibility, historical provenance conflicts, orphan state, the one-key canary candidate, and whether the queue-state SHA stayed unchanged. It does not POST to the API, write job/queue/capture state, create a model lock, or call the model; its lock check only probes an existing lock file without holding it. Supply hashes from one coherent GET eligibility snapshot and keep the JSON receipt outside the source tree:

```sh
/Users/lexi/Library/Application\ Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python \
  -B ops/run_manager_flash_announcements.py \
  --state-root "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench/manager_workbench" \
  --capture-root "<capture-root-from-local-service-config>" \
  --job-id "<source-job-id>" \
  --resume-source-job-id "<source-job-id>" \
  --resume-frozen-batch --resume-dry-run --max-model-calls 1 \
  --source-input-sha256 "<source_input_sha256>" \
  --source-progress-sha256 "<source_progress_sha256>" \
  --source-queue-state-sha256 "<source_queue_state_sha256>"
```

No visible model/capture canary was run for this writer handoff. The independent reviewer must inspect the actual source diff and frozen PASS scope before the controller starts the one-request canary. A prompt `changes` conflict during that canary stops the run as partial; do not adjust the frozen prompt or retry failed parts.

## Writer verification

Focused test and dry-run receipts are recorded in the `announcement-resume-20261018/writer/` evidence folder. The final read-only plan used the hash-bound saved V35 shared-data root and source input/progress/queue SHA values. It returned `READ_ONLY_PLAN` with 24 `SUCCEEDED`, 15 `FAILED`, 5 `PENDING`, and 1 planned `RUNNING` orphan; all 5 pending rows were blocked by verified historical successes whose source and chunk-plan provenance differs. It reported `historical_success_conflicts: 5`, `pending_eligible: 0`, `recoverable_orphan_count: 1`, `canary_candidate: null`, `model_calls: 0`, and an unchanged queue-state SHA (`a2683ea713dd16e09037dbbd52fb95bff4137e892b8ebaf443e8a9bcd33f4243`). The null dry-run canary is expected: only a real resume worker can perform the owner-clear interruption transition; the isolated test verifies that transition selects one request and cannot repeat it after a terminal canary failure.

The API snapshot and UI regression show the hash-bound resume button with `可恢复中断分块 1 · 本次提交最多 1 个模型请求`; only an explicit click sends the dedicated resume POST. No live API POST, model/capture call, service action, or candidate deployment was performed. Build the frontend into a candidate-owned output directory after independent Reviewer PASS, include the changed runner and V4 workbench source in the candidate, then follow the activation/rollback runbook's all-date submission lock and readback checks. Do not copy over the active release or deploy before the controller's review decision. `REVIEWED`, `BEHAVIOR_VERIFIED`, runtime integration, and natural-result acceptance remain separate states; the writer's test results are not the independent reviewer verdict.
