# Issue 33 monitor review and implementation handoff

## Role and scope

This participant initially performed a read-only review of the new runner,
official adapter/guard and attached original resource monitor. The parent then
assigned implementation of a narrowly scoped monitor wrapper prototype and its
tests. This report is therefore an implementation handoff, not an independent
approval of the final wrapper, full runner, local binding or real evaluation.

No real Mac candidate scores, truth, model or registry were opened. No fit,
predict, model load, dependency installation or real evaluation was performed.

## Confirmed initial P1 findings

1. A failure writing `EVALUATION_RUN_RECEIPT.json` after successful synthetic
   evaluation escaped before terminalization. A minimal fault-injection probe
   using the actual worker and official synthetic registry yielded:

   ```json
   {"blocked_receipt":false,"error":{"message":"SYNTHETIC_RUN_RECEIPT_WRITE_DENIED","type":"OSError"},"events":["RUN_STARTED"],"monitor_calls":1,"synthetic_only":true,"terminal_receipt":false,"worker_status":"COMPLETED"}
   ```

   The parent owns the runner fix and final verification of this finding.

2. The original monitor could propagate a `KeyboardInterrupt` out of its
   sampling loop without stopping its spawned worker. The isolated probe
   `probe_monitor_interrupt.py` produced:

   ```json
   {"error":{"message":"SYNTHETIC_REVIEW_INTERRUPT","type":"KeyboardInterrupt"},"failure_evidence_exists":false,"new_children_still_alive":1,"synthetic_only":true,"trace_exists":false}
   ```

   The probe's finally block terminated and joined its test-owned child. The
   new wrapper addresses this abnormal monitor-return path without modifying
   the original helper, retrying the monitor or restarting the worker.

## Integrated source snapshot after partial-handle fix

- Prototype: `analysis/monitor_adapter_candidate.py`
- SHA256: `f74841d13c7c5be2aa229db9717fb3d4938eb15b1982c548ea887a57615cbd2d`
- Integrated launcher: `candidate/src/run_rff_saved_evaluation.py`
- SHA256: `115f84e85777a3f002e01c441f62f0fe179adbac72e3c2ecdfaa91adbc5802ba`
- Test: `candidate/tests/test_rff_saved_eval_monitor.py`
- SHA256 with `ADAPTER_PATH` pointing to the actual launcher:
  `41f861cf4756b260fc5841407424dcc2fbd09029c990d651343550d658f38fc6`
- Unchanged original resource helper SHA256:
  `9d0792a8e582d0345c83ddaf83a15612a5629b5f0460833b4715068324ff2752`

The parent has moved `_check_monitor_backend`, `_defer_sigint_during_abort`
and `_monitor_once` into the launcher and restored the test's `ADAPTER_PATH`
to that launcher. The source hashes above were read back from disk, and the
three function source segments were compared directly with the tested prototype:
all three matched exactly. Final integrated-suite validation belongs to the
parent. The wrapper uses only stdlib facilities; the new narrow start guard
observes `multiprocessing.popen_spawn_posix.Popen` during this exact Process's
start and restores the temporary hook afterward.

`_monitor_once` calls the original monitor once. A Process proxy retains the
actual spawn handle and records whether `start()` was attempted and returned;
the actual process object remains the object serialized by multiprocessing.
The wrapper also retains the original monitor's most recent known descendant
map. Unexpected exceptions invoke the original cleanup helper once, record
actual exit/cleanup observations, write a new abort receipt if possible and
rethrow the original exception. Normal returns do not invoke extra cleanup.
Repeated SIGINT during this bounded abort handling is deferred and recorded.
A cleanup or receipt-write failure remains explicit; it does not replace the
original exception. The in-memory observation remains on `exc.rff_monitor_abort`.

`_check_monitor_backend` performs one original parent-only RSS observation
before RUN_STARTED. An OS backend exception or nonpositive/invalid observation
fails with `MONITOR_BACKEND_PREFLIGHT_FAILED`; an already exceeded explicit
bound fails with `RESOURCE_RSS_ALREADY_EXCEEDS_BOUND`. It does not create a
process, assign a cap, write a trace or read route input files.

## Start-phase evidence that the runner must honor

The original `SPAWN_START` error handler includes context-manager exits after
`process.start()` succeeds. A real-spawn test proves the original failure file
can therefore claim `PROCESS_NOT_STARTED` despite a real PID. The wrapper's
abort record retains that PID, `process_start_attempted=true`,
`process_start_returned=true` and its cleanup/exit result. The runner must reject
the original no-spawn assertion when this evidence contradicts it.

The earlier 16-case prototype also demonstrated a second failure: `_Popen` can
launch a child before `BaseProcess.start` assigns its handle. The previous
prototype merely recorded UNKNOWN and left emergency cleanup to the test
harness. **That earlier behavior was not sufficient closure and has been
superseded by the partial-handle fix described here.**

The final wrapper observes `Popen.__init__` before construction, and only captures
instances whose `process_obj` is the exact real Process being started. If start
raises after launch but before the normal assignment, it adopts the unique
already observed positive-PID handle into that same Process's `_popen` and,
when present, `_sentinel`, registers ordinary multiprocessing ownership in
`_children`, then calls the original process-tree cleanup helper. It neither
constructs another Process nor restarts the worker. The original start exception
is retained and `process_start_returned` remains false.

SIGINT is deferred only during this short start/handle-assignment interval. If
start returns successfully after a deferred SIGINT, the wrapper immediately
raises KeyboardInterrupt into the same abort-cleanup path. The Popen constructor
hook and prior signal handler are restored on both success and failure.

Three fault-injection cases execute real spawn: failure after `_Popen` returns,
failure within its constructor after launch, and a real SIGINT before the
BaseProcess assignment. Each passing test asserts the actual child's `poll()`
is non-None **before** the test harness's emergency cleanup can run. Thus the
wrapper itself ends these children. A counterexample with no observed Popen
instance retains UNKNOWN and does not invent a handle, PID, cleanup success or
zero activity.

The top-level abort record supplies `process_creation_count`,
`process_start_attempted_count`, and `process_start_returned_count`. Each worker
supplies `pid`, `process_start_attempted`, `process_start_returned`,
`process_state`, `exit_code`, cleanup observations and errors. The final delta
also supplies `popen_instances_observed`, `popen_handle_recovered`,
`popen_recovery_error`, `start_sigint_guard_installed` and
`sigint_deferred_during_start`. A strict
no-start proof is creation count zero, or all created processes never having
attempted start and having no PID, with matching source and execution identity.

The original cleanup helper's optional `monitor_error` argument unconditionally
enters `enumeration_errors` and prevents a confirmed result. The wrapper keeps
the original exception in the abort record and does not pass a generic
KeyboardInterrupt or file-write OSError as a false enumeration failure. Actual
cleanup errors returned by the helper remain untouched and prevent confirmation.

## Verification and limits

The first eight tests were RED while the wrapper was absent. Additional
start-phase and backend-preflight tests were observed RED before those fields
and the preflight function were added (`monitor_start_phase_red.log` and
`monitor_preflight_red.log`). The earlier 16-case green log remains historical
evidence in `monitor_wrapper_final_green.log`; it is superseded by the final
partial-handle tests and implementation.

The strengthened existing partial-Popen test first failed because the actual
child remained alive (`monitor_partial_handle_red.log`). The constructor,
signal-assignment and no-handle counterexamples then produced three failures
and one missing-field error (`monitor_partial_handle_cases_red.log`). After the
fix, the isolated monitor command ran **19 tests, all passing** in 0.414 seconds;
output is `monitor_partial_handle_green.log`. That run tested prototype SHA
`f74841d13c7c5be2aa229db9717fb3d4938eb15b1982c548ea887a57615cbd2d`
with test SHA
`9abf89475136fcf56f298b65d2ce68b29dae5b6ef4a1205461699ef43303d250`
(before its sole `ADAPTER_PATH` change back to the integrated launcher).

The tests execute real multiprocessing spawn, child liveness, signals, join,
the original monitor and its original cleanup functions. Native metadata,
worker targets and process/RSS snapshot rows are explicit test fixtures. The
container's real OS backend did not provide consistent process observations;
the initial failures are preserved in
`monitor_original_backend_failure_excerpt.log`. The tests' snapshot fixture
contains only this test's real multiprocessing child IDs/liveness and
synthetic RSS values; it never inspects or signals unrelated host processes.

Consequently this is evidence for abnormal-exit lifecycle behavior and source
integration, not Mac-native RSS enforcement, L04, a release of the new binding,
real 2024 metric parity or an improvement in real hit rate. Those remain subject
to the separate local review and controller release.
