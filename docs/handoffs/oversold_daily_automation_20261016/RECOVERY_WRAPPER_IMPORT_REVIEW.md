# Independent recovery-wrapper import preflight review

```text
status: PASS_RECOVERY_WRAPPER_IMPORT_PREFLIGHT
reviewer_identity: /root/oversold_daily_review
writer_identity: oversold_daily_writer
scope: readonly_identity_preflight_only
candidate_release_id: oversold-daily-cache-20261016-r1
candidate_release_manifest_sha256: 03f1c61fe881039b286bd4d0d9acbcb29d32593747e7c0119b8e3c261237bfb2
recovery_wrapper_sha256: 99402d1a0adbc50e63512369f91cbd159f287aadf31271b0ebf5c364a1fc3cad
focused_tests: 2 passed
active_candidate_pid: 39211
activated: true
live_recovery: CANNOT_CONFIRM
```

The wrapper now loads `ops/api_release_integration.py` by its exact workspace path using `spec_from_file_location`, rejects symlink/path aliases, checks the pinned SHA-256 `86804204fae3484bf4277e6b2d4cdb7b1dea34ea7af530ebe2a036d845246f31`, and verifies both the import spec origin and loaded module origin. The candidate-only shadow-module test confirms that a candidate `ops/api_release_integration.py` is not selected; the changed-source test confirms a mismatched helper SHA fails closed.

The configured Python 3.14.6 interpreter ran with `-S` in two read-only plan invocations. With `PYTHONPATH` taken from the active plist, and with the recovery child's full `app:site-packages:upstreams:app` path, each invocation completed the wrapper's import-time identity preflight and returned `RECOVERY_PLAN_ONLY`, release `oversold-daily-cache-20261016-r1`, manifest SHA `03f1c61fe881039b286bd4d0d9acbcb29d32593747e7c0119b8e3c261237bfb2`, and PID `39211`. The preflight consequently verified the active scheduler's current PID, plist, release manifest, app inventory, source files, configured interpreter/module, and process cwd through the existing identity checks.

Focused verification used:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q --tb=short --basetemp=/tmp/pytest-oversold-cache-wrapper-review docs/handoffs/oversold_daily_automation_20261016/test_recover_oversold_cache_wrapper.py
2 passed in 0.01s
```

Exact reviewed artifact hashes:

- Wrapper: `99402d1a0adbc50e63512369f91cbd159f287aadf31271b0ebf5c364a1fc3cad`
- Focused test: `f01c3f70b3a341f08f6eb4272ba63fbba422b05df0b2a0f87ae813c8c944b394`
- Pinned workspace inventory helper: `86804204fae3484bf4277e6b2d4cdb7b1dea34ea7af530ebe2a036d845246f31`
- Existing recovery core, unchanged: `b757420def3382d363331d8a6bc46c28eced034bdf220f2d7fa60a639d00da5f`

This PASS is limited to helper import/source binding and active-scheduler identity preflight. The candidate is already active; this review did not run `--run`, enter the recovery driver, call `driver.tick`, alter service state, write owner data, or make network requests. Actual recovery outcome, API/UI readback, and natural scheduled behavior remain `CANNOT_CONFIRM`.
