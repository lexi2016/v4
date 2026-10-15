# Independent runtime release review

```text
schema_version: v4.oversold_daily_scheduler_runtime_review.v1
status: FAIL_RUNTIME_RELEASE
behavior_verified: FAIL
candidate_release_id: oversold-daily-auto-20261016-r1
candidate_release_manifest_sha256: d9750660f989198e9000b1686801ac514def52e27c5dff75c93bdccb3a4a05d6
writer_identity: oversold_daily_writer
reviewer_identity: /root/oversold_daily_review
reviewed_at_utc: 2026-10-15 18:02:39 UTC
```

The runtime candidate is **not approved for activation**. The preparation receipt and candidate identity are internally consistent, but the cutover helper cannot identify the running base/candidate process using the actual scheduler launcher command line. The documented recovery plan command also does not match the recovery helper's CLI.

## Findings

**P1 — cutover process-root checks do not match the scheduler's real argv.** The activation preflight requires the old process command to contain `base_root/app` ([`scheduler_release_cutover.py:233-238`](scheduler_release_cutover.py)), and attach confirmation requires the candidate app root in that command ([`scheduler_release_cutover.py:110-119`](scheduler_release_cutover.py)). The process lookup uses `ps ... -o command=` ([`scheduler_release_cutover.py:63-67`](scheduler_release_cutover.py)). The active and candidate launchers instead `cd` to the app and put its root in `PYTHONPATH`, then `exec` Python as `-S -m ops.run_v35_macos_scheduler_daemon` ([candidate launcher:63-64, 94](</Users/lexi/Library/Application Support/com.lexi.v4.local/releases/oversold-daily-auto-20261016-r1/app/ops/launch_v35_macos_scheduler.sh:63>)). A read-only `ps -ww -p 90252 -o pid=,command=` showed the receipt-identified process running that module with no base app-root string in argv. Therefore, if the label still points to PID 90252, activation will stop at `ACTIVE_PROCESS_RELEASE_BINDING_MISMATCH`; after bootstrap, candidate attach will likewise time out. The same path-string assumption in `_wait_detached` and `_scheduler_processes_for_root` can also treat a still-live process as absent when its argv lacks the expected app-root string. **CANNOT_CONFIRM:** launchd label-to-PID state was not re-read because this review made no `launchctl` calls. Use a process identity check that matches the actual launcher/runtime (and independently confirms PID exit) before activation can pass.

**P2 — the recovery plan's recorded `--plan` command is invalid.** [`SCHEDULER_CUTOVER_PLAN.json:102`](docs/handoffs/oversold_daily_automation_20261016/SCHEDULER_CUTOVER_PLAN.json) and [`RUNTIME_PREPARED_RECEIPT.md:21`](docs/handoffs/oversold_daily_automation_20261016/RUNTIME_PREPARED_RECEIPT.md) say the default `--plan` command was run. The helper parser accepts `--run`, `--authorization-ref`, and hidden `--child`, but no `--plan` ([`recover_oversold_20261016.py:106-120`](docs/handoffs/oversold_daily_automation_20261016/recover_oversold_20261016.py)). Running the recorded command with the configured scheduler interpreter returned `error: unrecognized arguments: --plan`. Running the helper with no mode flag returned `RECOVERY_PLAN_ONLY` for source day `20261015` to target `20261016`, without a formal run. Correct the recorded command/claim or add and validate the advertised flag. The future `--run` path itself requires an authorization reference and checks that the target is the current Hong Kong date before creating the owner service ([`recover_oversold_20261016.py:119-140`](docs/handoffs/oversold_daily_automation_20261016/recover_oversold_20261016.py)).

## Verified preparation evidence

- Candidate manifest SHA-256 is `d9750660f989198e9000b1686801ac514def52e27c5dff75c93bdccb3a4a05d6`; staged plist SHA-256 is `91d83bd16af4b7932fb07007651339ee3978aa8a293d72e25e828962c8403072`. Both match the preparation receipt.
- The active plist and saved preimage both match `cc2d35ed4c156b0e741276b49966ea6430d74f96359c9d4103c2800afc0c5344`; active manager config matches `65684e5eb7657390747c089db74047d6a2c67d7f5de1bd3fe757a62f120965ca`. Its scheduled lanes remain `US_MAPPING` and `OVERSOLD`.
- Recomputed physical inventories match the manifest. The only changed app paths are the six frozen delta files; all 1,022 non-delta entries and their aggregate SHA match the receipt. The staged plist changes only the five release-selector environment keys, `ProgramArguments`, and `WorkingDirectory`; safety flags remain false and launch policy fields are preserved.
- The configured scheduler interpreter exists, is executable, and reports Python 3.14.6. All seven module paths and SHA-256 values in the candidate import probe match the candidate files. Both activation and rollback no-action CLI invocations returned `PREPARED_ONLY` with `launchctl_called=false`.
- The recovery helper's no-argument plan output preserves the 20261015-to-20261016 exact-date scope, uses current Asia/Hong_Kong time, and states no network/formal run occurred. Cache hits, API/UI readback, and natural-slot behavior remain unverified.

No `launchctl` command, network request, activation, rollback, or formal recovery run was performed. Runtime installation, live API/UI behavior, and natural scheduled execution remain `CANNOT_CONFIRM`; `NATURAL_VERIFIED` is not claimed. Research safety remains `RESEARCH_ONLY=true`, `PRODUCTION_ALLOWED=false`, `BUY_GATE_UPDATED=false`, and `ORDERS_SENT=false`.
