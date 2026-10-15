# OVERSOLD scheduler release preparation

Status: `PREPARED_NOT_ACTIVATED`; runtime installation and launchd activation were not performed.

Candidate release: `oversold-daily-auto-20261016-r1` at `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/oversold-daily-auto-20261016-r1`.
Candidate release-manifest SHA-256: `d9750660f989198e9000b1686801ac514def52e27c5dff75c93bdccb3a4a05d6`.
Candidate staged plist SHA-256: `91d83bd16af4b7932fb07007651339ee3978aa8a293d72e25e828962c8403072`.
Active scheduler plist preimage SHA-256: `cc2d35ed4c156b0e741276b49966ea6430d74f96359c9d4103c2800afc0c5344`.
Active manager config SHA-256: `65684e5eb7657390747c089db74047d6a2c67d7f5de1bd3fe757a62f120965ca`; the existing config remains the binding, with scheduled lanes `['US_MAPPING', 'OVERSOLD']`.
Base app physical inventory SHA-256: `5d7feb6a022a0b4e93f487659f3a7693025515179bd628b096d8d3ab8facc4e3`; candidate app physical inventory SHA-256: `5973d71c2e2cb2c5174c07e1350fd5ab6ebed1ce871bdcedcf0ac7cc53be206c`.
Non-delta entries preserved: `1022`; inventory SHA-256 `0064809cb6742c4c8484f2d5d8affeead6bbfb14570eca8e1c2a6669c80eebd7`.

The candidate app was copied from the release selected by the fresh LaunchAgent plist. The recorded six-file patch was applied to that copy; complete base and candidate SHA/mode inventories are in the candidate `release-manifest.json`. The staged LaunchAgent changes only the release selectors (`V35_APP_ROOT`, release id/manifest path/hash, `PYTHONPATH`), `ProgramArguments`, and `WorkingDirectory`; manager config, external roots, schedule, KeepAlive/RunAtLoad, and safety flags remain the same.

The actual scheduler interpreter `/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260904T081111Z-v35-strict-stage-acquisition-v15/runtime/venvs/v3.5-mac/bin/python` imported the daemon and all six candidate modules from the candidate app root. Detailed module paths and SHAs are in the machine receipt.

Independent source review: R2 PASS_CANDIDATE, source review SHA-256 `fc706b6ab88fabcbf8ba551ff7993e08a70990a599f6fa904ccfc1501eed23e5`. This review did not approve activation.

Activation must remain blocked until a separate runtime-release review and explicit authorization are recorded. The prepared activation helper waits for the old PID to exit, the launchd label to disappear, and a settle interval before bootstrapping the candidate; rollback is CAS-bound to the exact candidate plist and restores the saved byte-for-byte active preimage.

The no-action activation, rollback, and recovery plans are in `SCHEDULER_CUTOVER_PLAN.json`. `activate_scheduler_release.py` and `rollback_scheduler_release.py` print `PREPARED_ONLY` unless their explicit action flag is supplied; activation also requires a separate runtime review receipt bound to the candidate-manifest SHA and an authorization reference. The recovery helper supports both its default plan-only mode and explicit `--plan`; the configured scheduler interpreter ran the explicit flag and returned `RECOVERY_PLAN_ONLY` without service imports, network access, or a formal run. Its future `--run` path is limited to the existing `oversold_daily_20261015_20261016` cursor, requires the target to remain the current Hong Kong date, uses the actual current time, and uses the existing exact-date owner/cache path. Actual per-security cache hits remain `CANNOT_CONFIRM` until row-level capture-record readback; no existing plan or manual work is deleted.

## Runtime-review repair validation

The first runtime review remains preserved as `RUNTIME_INDEPENDENT_REVIEW.md` with status `FAIL_RUNTIME_RELEASE`; this writer receipt does not replace independent review. The cutover helper now binds process identity through the launchd label PID and loaded plist path, selected app/release/runtime/PYTHONPATH/config fields, actual process cwd, configured Python interpreter, and `ops.run_v35_macos_scheduler_daemon` module command. The helper reads only those named plist selectors; it does not dump or record the process environment. Detach confirmation requires both the launchd label to be absent and the exact preflight PID to be absent before and after the settle interval. Fresh plist/config CAS and byte-for-byte preimage rollback checks remain in place.

Read-only identity readback at `2026-10-15T18:11:40.760806Z` confirmed current PID `90252` is owned by `gui/501/com.lexi.v35.scheduler` and matches base release `hk-tdx-conflict-repair-main-20261015-r2` through the combined selector, cwd, interpreter, and module checks. The exact plan command recorded in `SCHEDULER_CUTOVER_PLAN.json` ran under the configured interpreter and returned `RECOVERY_PLAN_ONLY`; default activation and rollback helper invocations still returned `PREPARED_ONLY` with `launchctl_called=false`. The new focused runtime guard tests report `7 passed`; see `test_scheduler_release_runtime_guards.py`.

The candidate remains `PREPARED_NOT_ACTIVATED`. No `launchctl` mutation, activation, rollback, formal recovery, network request, API/UI readback, or natural slot was performed. Independent runtime-release review of the updated helpers is still required.

Runtime review receipt contract for the activation helper: JSON schema `v4.oversold_daily_scheduler_runtime_review.v1`, `status=PASS_RUNTIME_RELEASE`, `behavior_verified=PASS`, `candidate_release_manifest_sha256` equal to the candidate SHA above, `writer_identity=oversold_daily_writer`, and a distinct non-empty `reviewer_identity`.

`CANNOT_CONFIRM`: the current active scheduler process still runs the base release; no candidate process was started. No live TDX refresh, formal scheduled recovery, API/UI readback, or natural slot was performed. The import probe establishes only that the configured scheduler interpreter resolves the frozen modules from the isolated candidate.

Research safety remains `RESEARCH_ONLY=true`, `PRODUCTION_ALLOWED=false`, `BUY_GATE_UPDATED=false`, `ORDERS_SENT=false`.
