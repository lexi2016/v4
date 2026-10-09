# Independent review of the RFF saved-evaluation runner

Reviewer: `/root/metric_parity`  
Scope: source and synthetic fixtures only; no production data, model, real registry, or Mac execution.  
Review state: **FINAL — scoped source review passed; no remaining definite P0/P1 in the reviewed runner, contracts and registration relationships. R1, R2 and R3 are closed.**

## Reviewed artifacts

The runner was written by the root agent and the monitor-wrapper author; contracts and registration were written by the lifecycle agent. This reviewer did not edit any of those three production files or their tests. The reviewer previously wrote the frame evaluator and worker, which are referenced for interface checks but are not claimed here as independently reviewed code. The source changed during review as the root incorporated findings; line references below identify the reviewed stage explicitly.

Final file identities, directly recomputed by this reviewer after integration:

| Artifact | SHA-256 |
| --- | --- |
| `candidate/src/run_rff_saved_evaluation.py` | `115f84e85777a3f002e01c441f62f0fe179adbac72e3c2ecdfaa91adbc5802ba` |
| `candidate/src/rff_saved_eval_contracts.py` | `35b9f88b8183f8980333bfe4e06f37b3ef3e2acbea7a0fc6904b1d130ef058b7` |
| `candidate/src/rff_saved_eval_registration.py` | `e25f3312332547f71f9edab2b76a49e20921ca1fb3c29d0c0face7211fd03ce0` |
| `candidate/tests/test_run_rff_saved_evaluation.py` | `b18b3cc91e59dc18298249ce08e15e92358d0f7a7833ef3eb782831b005a3ec7` |
| `candidate/tests/test_rff_saved_eval_monitor.py` | `41f861cf4756b260fc5841407424dcc2fbd09029c990d651343550d658f38fc6` |

The initial 15 runner integration cases and their later deltas were read; the final runner file contains 20 integration cases and the final monitor file contains 19 cases. No full suite was rerun by this reviewer. Two targeted synthetic probes were executed by this reviewer to confirm R1 and the runner-side contradictory-observation behavior in R2. The root and monitor author own implementation and suite execution; their final evidence is attributed separately below.

## Confirmed finding R1: optional evidence failure could bypass the owed terminal

**Severity: P1 at initial review; closed in the integrated source.**

In the initial runner, `_optional_json` performed `path.exists()` outside its `try` (then line 85), and the extra evidence loop and `trace.exists()` ran outside the post-start protection (then lines 369–376). A permission error while probing an optional artifact could therefore escape `_execute_bound` after a durable `RUN_STARTED`, before its single terminal attempt.

The targeted probe used the existing generated integration fixture, its explicit `proven_no_spawn` monitor substitution, and a `Path.exists` patch that raised `PermissionError("SYNTHETIC_OPTIONAL_EVIDENCE_STAT_DENIED")` only for the generated output's `METRICS.json`. It did not modify product source or touch a real registry. Observed output:

```text
exception: PermissionError / SYNTHETIC_OPTIONAL_EVIDENCE_STAT_DENIED
new_events: [RUN_STARTED]
monitor_calls: 1
run_receipt_exists: false
terminal_receipt_exists: false
```

The root accepted the finding. In the final runner, `_optional_json` places the stat inside its exception handler (lines 84–94), and the additional evidence reads have an outer `BaseException` guard (lines 397–407). That guard keeps the previously obtained activity and truth observations and downgrades the decision to `CANNOT_CONFIRM`; it does not retry the worker or replace observations with zero. The new test `test_optional_evidence_stat_error_cannot_skip_failure_terminal` checks that the execution still appends exactly one terminal. The start/run receipt failure tests cover the corresponding write windows. These cases passed in the root's final suite.

## Confirmed finding R2: an old no-spawn claim can contradict actual process evidence

**Severity: P1 at initial review; closed in the integrated counter-classification source.**

The current packaged `resource_tree.py` wraps both `process.start()` and the exits of its DYLD/thread context managers in one `try` (lines 714–735). Any exception from that block writes `exit_code_state=PROCESS_NOT_STARTED` and `stage=SPAWN_START`. An exception from a context-manager exit occurs after `process.start()` can already have returned successfully; the old failure record alone therefore does not prove that the worker never started.

The pre-fix runner `_observations` read only the old `EVALUATION_MONITOR_FAILURE.json` when deciding that a worker did not start (then lines 135–176). Its acceptance conditions verified descriptor/source identity and required missing status/marker, but did not consult the wrapper's actual process observation. Consequently a started worker that was promptly killed, before it wrote status or a truth marker, could be represented as all-zero activity and truth counts.

The wrapper prototype in `analysis/monitor_adapter_candidate.py` retains a process handle and writes a separate `EVALUATION_MONITOR_ABORT.json` including PID and cleanup state. When that record, or the in-memory abort observation, says a process started, it must defeat a conflicting old `PROCESS_NOT_STARTED` claim. Without verified worker counters, the runner should retain `UNKNOWN`/`CANNOT_CONFIRM` counts. Cleanup completion is not proof that no evaluation activity occurred.

The root and monitor reviewer were notified. The implemented real-spawn regression makes a synthetic context manager raise after its `yield`: the packaged helper reports the old no-start claim, while the wrapper sees an actual PID. No historical helper file was modified.

A second targeted runner probe has now confirmed the accounting consequence using generated observations only. Its synthetic monitor wrote the old `PROCESS_NOT_STARTED` record, then raised an exception with in-memory `rff_monitor_abort` containing `process_creation_count=1`, an explicitly synthetic PID of 12345, and `JOINED_AFTER_ABORT_CLEANUP`. The run receipt preserved that PID in `error.monitor_abort`, yet simultaneously reported:

```text
terminal: CANNOT_CONFIRM
observed_worker_accounting.status: KNOWN_NOT_LAUNCHED
truth_accounting.status: KNOWN_NOT_LAUNCHED
evaluation_truth_decode_attempts: 0
```

This probe did not launch a child; it tests reconciliation of contradictory generated evidence. It proves that adding the abort artifact to the evidence list alone is insufficient. The classification must consider both durable abort evidence and the in-memory observation, because an abort-evidence write can itself fail.

In the first integrated-wrapper delta, runner `_observations` (lines 136–223) now consumes the attached monitor error as well as the durable abort file. The old helper's `PROCESS_NOT_STARTED` record cannot prove zero on its own. A no-start abort must have the exact execution/route/candidate/spec/binding/source identity, source-file set, target descriptor, trace path, typed zero start-attempt/start-return counts and workers explicitly marked not attempted/not returned with no PID. Every available abort observation must agree. A positive PID, an attempted but incomplete start, or a disagreement defeats that proof. The new integration tests cover both a conflicting in-memory abort without a file and an old no-spawn record without wrapper proof. This closes R2's false-zero result.

There is a related startup boundary: in the inspected local Python implementation, `BaseProcess.start` assigns `self._popen = self._Popen(self)`. The spawned-POSIX `_launch` creates the OS process before finishing pipe writes and cleanup. An exception while constructing `_Popen` can therefore leave the outer Process without a PID despite an attempted start. A created Process with `pid is None` is not by itself a proof that startup was never attempted. The final integrated counter classifier now treats this as unknown, correctly closing the false-zero part of R2. Its cleanup consequence is R3 below.

## Final-delta finding R3: partial Popen failure can retain a live unmonitored worker

**Severity: P1 at the first integrated-wrapper delta; closed in the final integrated source and focused real-spawn regressions.**

The first integrated wrapper correctly distinguished `process_start_attempted` from `process_start_returned`. However, in that reviewed 722-line runner its lines 601–607 merely set `START_ATTEMPTED_PID_UNAVAILABLE` and continued if the outer Process had no PID. It did not attempt cleanup of an already created OS child whose `_Popen` handle was not assigned back to the outer Process.

The original real-spawn test added by the monitor reviewer, `test_partial_popen_exception_without_process_pid_remains_unknown`, called the real `_Popen`, then raised before `BaseProcess.start` received its return value. The test explicitly asserted `launched[0][1].poll() is None` after the wrapper returned. Only the test's separately retained handle and `addCleanup` stopped that child. Thus the original test proved truthful unknown accounting, but also proved a live child could outlast the production wrapper's return.

The runner could then append a `CANNOT_CONFIRM` terminal while evaluation continued outside the resource monitor. Unknown counts were necessary, but did not prove process-tree convergence. The root accepted the finding and the monitor author changed the regression to require the wrapper itself to terminate the child. The RED log shows the expected failure: `wrapper left the real partial-start child alive`.

The final `ProcessProxy.start` observes `popen_spawn_posix.Popen.__init__` before construction, only for `process_obj is self.process`. If the real start fails, it may adopt exactly one already observed Popen object with a positive integer PID, restore that object's original sentinel and register the same Process with standard multiprocessing ownership. It does not construct another Process, restart a worker or invent a PID. The existing `_safe_terminate_descendants` handles cleanup once. An unobserved or ambiguous handle remains explicitly unconfirmed.

The short start interval defers SIGINT until the real Process handle is assigned; a pending interrupt immediately enters the same abort cleanup. Nested `finally` blocks restore the original Popen initializer and signal handler. An original start exception remains the primary exception, with recovery/cleanup failures recorded separately.

The reviewer read the new source and RED/GREEN logs. The final focused tests cover an exception after `_Popen` returns, an exception inside the Popen constructor after real spawn, and an actual SIGINT before `BaseProcess` assigns its handle. All three now assert that the actual child has exited **before** test-harness cleanup. The no-Popen case verifies that the wrapper cannot invent a handle or claim confirmed termination. The monitor author's focused suite passed 19/19.

The root integrated the reviewed prototype SHA `f74841d13c7c5be2aa229db9717fb3d4938eb15b1982c548ea887a57615cbd2d`. This reviewer directly compared the entire final runner section from `_check_monitor_backend` to immediately before `_run_real` against that prototype and obtained byte-for-byte equality after trimming outer whitespace. The final monitor tests point to the actual runner, and the root's final suite passed those tests there. R3 is closed for the confirmed counterexamples.

## Lifecycle and counter review

| Area | Source assessment |
| --- | --- |
| Admission | Explicit resources, bound source/metadata snapshots, new output/trace paths, the old single fit debit, native runtime, local review and parent release are checked before the real CLI claims a new execution. The internal generated-fixture seam is explicitly documented separately. |
| Durable start | A start receipt carries the execution/route/candidate, spec/binding/source SHA values and the appended start-event SHA. Worker launch follows the durable receipt and a dependency/release drift check. |
| Start append exception | The runner performs one readback. A proven durable start is closed without worker launch; an unconfirmed start does not cause an append retry or worker launch. |
| Terminal append exception | A single terminal append attempt is followed by one runner readback; an already durable terminal is accepted without reappend. An unconfirmed terminal produces explicit blocked evidence and no retry. The underlying official adapter also performs its own mandatory durable validation. |
| Historical budget | Before/after accounting must retain the old real-fit debit of one. The new execution is structurally zero debit; actual worker observations are separately named. |
| Worker observations | Validated status can report actual zero activity; absent/invalid worker evidence produces null observations. A durable truth marker supports an attempt with unknown completion. Known no-start requires the wrapper's exact, noncontradictory actual-start observations. |
| Truth access | The worker verifies one raw truth snapshot before decode, writes the durable decode-start marker, decodes once and retains actual partial counts on failure. Runner receipt construction and terminal readback do not reread the truth. |
| Completion | Success requires native child verification, observed zero activity, truth decode completed once, both control-label artifacts decoded, worker exit zero, final fsync checks and complete result/metrics SHA identities. Missing or contradictory evidence is not promoted to completed. |
| Evidence ceiling | Metrics, result, run receipt, terminal and registration retain `DIRECTION_ONLY`, research-only safety flags, and promotion false. No successful development gate changes that ceiling. |

These are source assessments, not claims of a real Mac run. In particular, a terminal append can fail because the official registry or its validated prefix becomes unavailable; the code must make one appropriate attempt and report that it could not confirm durability, rather than inventing a terminal or retrying.

## Minimum comparison output

The normal completed output is sufficient for the requested RFF-versus-control comparison. `EVALUATION_RUN_RECEIPT.json` includes all three arms with selection slots, known hits, unknown selections, lower/upper precision, confirmed NEW events, unique hit episodes and confirmed-episode coverage. It includes both paired-precision bounds/denominators and the unchanged development thresholds (`PLUS lower > 0`, `BASE34 lower >= 0.03`), original promotion gates and the promotion-blocking decision.

The SHA-linked `METRICS.json` retains the full arm dictionaries from the original evaluator, including binary probability diagnostics, plus the separately labeled raw-margin AP diagnostics, paired daily data and copied original gates. The compact run receipt does not repeat every probability field, but the complete deliverable does preserve them and its identity is checked. A `COMPLETED` technical evaluation therefore supplies the comparison without implying model promotion or changing the original evaluation definition. Actual numeric results remain uncomputed in this review.

## Independent contracts and registration cross-check

The final-delta review also read the production contracts' preparation, dependency closure, document loading and review/release validation, and the registration profile's claim, terminal, source-drift and observation paths. No additional definite P0/P1 was found in these reviewed cross-file relationships:

- `prepare` and `load_documents` cross-check the frozen candidate binding/spec, original output names and hashes, prediction seal, control references, truth/calendar references and original receipt chain. They do not change the historical candidate source manifest or call the candidate producer. Data input references stay opaque during preparation.
- The native helper and native reference preserve the old binding's dual path/SHA declarations; the runtime contract is tied to both its reference and the old candidate declarations. The runner derives the parent and child native spec through that bound helper.
- Frozen metrics are tied to the pinned score-aware helper's literal source path, with settings and package init in the same physical package. The two literal assignments are parsed without executing their expressions or extracting/reimplementing the accepted join.
- The official append policy follows the validator's actual implicit path, and its builder declaration must match the bound builder. New source files stay in the five-name route manifest; the runner's integrated wrapper is therefore covered by the runner's own file SHA without changing the manifest shape.
- A release must match the exact new spec/binding/source identity, explicit resource caps and fixed registry prefix, and must name a separate reviewer and parent controller. The review and release are snapshotted into the official start's authorization references and rechecked for drift.
- Registration keeps spec/binding bytes exact even on failure, checks the old registry prefix and route events under the original owner's lock, rejects duplicate execution/terminal events, and enforces structural zero debit without pretending it is an actual worker observation.
- A missing start receipt can close only as `CANNOT_CONFIRM`; dependency/source/release drift can also close only as `CANNOT_CONFIRM`. Core identity and official prefix validation are not bypassed to manufacture a successful terminal.

This cross-check is independent source review, not another execution of the contract or registration test suites, and is not a local parent release.

## Mac synthetic-fixture portability

The root's test-only `.resolve()` correction is appropriate. `common.plain_path` rejects symlink ancestors. A temporary directory returned through a macOS `/var` alias can otherwise fail before the intended synthetic test behavior is exercised. The three reviewed fixture roots now resolve their temporary directory once:

- `candidate/tests/test_rff_saved_eval_worker.py`, line 52;
- `candidate/tests/test_rff_saved_eval_registration.py`, line 63;
- `candidate/tests/test_rff_saved_eval_monitor.py`, line 57.

No production symlink rule was relaxed. Contract test fixtures had already resolved their temporary roots. This is a source-level portability correction, not evidence of native Mac test execution.

## Final verification evidence and attribution

The root executed the final new synthetic suite and reported exit code 0. This reviewer directly read and hashed the resulting `final_synthetic_verification.log`, found 142 individual `... ok` test lines, and checked its final summary:

```text
Ran 142 tests in 32.871s

OK
```

Log SHA-256: `7880d36c742711f15fd7ee51ff45a2cf4a3fd2035e6a32591a00283e4c771beb`.

The root also reported CLI help exit code 0 and unchanged before/after hash snapshots for all 11 source/test files in its final verification scope. Those executions and stability snapshots belong to the root; this reviewer does not claim to have independently rerun the 142-case suite or CLI help. The reviewer's direct evidence consists of source/test reading, the two initial generated runner probes, final-source hashing, source-block equivalence comparison and reading the authors' verification logs.

## Scope and remaining real-environment limits

Only the accepted PR5 worker/join is described as previously accepted. The packaged `resource_tree.py` has SHA `9d0792a8e582d0345c83ddaf83a15612a5629b5f0460833b4715068324ff2752` and is not the old frozen R2 identity; the new binding and review must cover these actual bytes plus the route wrapper. The accepted PR5 29/29 Mac receipt was not reopened or rerun.

The integrated abort provenance, no-spawn classification, terminal-protection corrections, actual-child cleanup repair and final source identities have been checked. No further definite P0/P1 was found in this review's scope. This verdict does not assert behavior under untestable OS denial, force-kill, or an unavailable runtime; such failures remain explicit errors or unconfirmed cleanup, never fabricated success.

The actual Mac interpreter/ABI and RSS backend, frozen package settings not supplied in the attachment, production saved scores/Top3/control schemas, and real metric values still require the new local binding's independent review and authorized execution. The current source preflights the parent-only RSS backend before a new official start and verifies the child native environment before data reads; synthetic substitutions do not establish native Mac parity. No real-data execution, parent release, registry mutation or promotion is authorized by this report.
