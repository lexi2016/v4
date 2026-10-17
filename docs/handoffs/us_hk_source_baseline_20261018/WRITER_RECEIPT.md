# Writer receipt — Issue 45 complete source baseline

**Writer state: IMPLEMENTED / HISTORICAL BASELINE EXPORT TESTED / FINAL FROZEN SNAPSHOT CANNOT_CONFIRM / READY FOR INDEPENDENT REVIEW.** This receipt covers the source handoff only. It is not the Issue 45 business repair and is not a `REVIEWED`, `BEHAVIOR_VERIFIED`, GitHub-sync, deployment, API/UI, or natural-run receipt.

## Result

- Exported 436 regular files (8,361,532 bytes): 434 canonical-worktree source copies and two derived test fixtures. Every staged file's source path, sampled SHA-256, staged SHA-256, and size is recorded in `SOURCE_EXPORT_MANIFEST.json`; all staged hashes and sizes match the manifest. The only staging symlink is relative and resolves within the local staged tree. The final source snapshot was frozen at `2026-10-18T00:40:31.612+08:00`; later canonical drift is outside this snapshot and is not pursued. Final `SOURCE_EXPORT_MANIFEST.json` SHA-256: `964bb055b6975fdd256c81afa6a2948d955f94aa1f1afabd1cd6aa8d8ebbd8ae`.
- During reconciliation, `v4/manager_workbench/api.py` was refreshed to SHA `d3dd953756ec4c9973f1b3ee7121f1b9530e17f231388655d7748c525a661636` / 18,672 bytes after its cached-recovery route addition. Its AST import set was unchanged. The directly related `v4/manager_workbench/announcement_update.py` was sampled from canonical at mtime `2026-10-18T00:40:18.333127+08:00`, copied as a complete file, and recorded as SHA `32bcc082586f32068a347676471f0e49adc7e2392b4123a1d9f5623155f3cbbd` / 117,289 bytes. It contains `start_cached_product_recovery`, which the API route calls. Its AST import set matches the prior staged file, including the existing `.inputs.capture_store` module; no new module dependencies were added. Only local staged copies and the manifest were updated; this writer did not change canonical code.
- The earlier isolated import smoke passed from `/tmp/v4-issue45-baseline-20261018-r3/staging` with `PYTHONPATH` and `PYTHONHOME` unset. It covered `ops.run_us_market_slot`, `ops.run_dispatcher`, `ops.run_v35_macos_scheduler_daemon`, manager supervisor/scheduler, `NativeAdapters`, `source_bindings`, mapping engine/catalog, and US market bridge. It also rejected any canonical worktree source path in `sys.path`. It predates the final `api.py` and `announcement_update.py` refresh; import-smoke status for the final frozen snapshot is `CANNOT_CONFIRM` pending independent review.
- The earlier focused existing suite ran from the isolated export: **225 passed, 3 failed, 1 explicitly deselected**. It predates the final `api.py` and `announcement_update.py` refresh; focused-suite status for the final frozen snapshot is `CANNOT_CONFIRM` pending independent review. The three earlier failures were reproduced with the same assertion messages against the then-current canonical worktree. They are preserved baseline source/test mismatches, not repaired here:
  - `tests/test_manager_us_mapping_bindings_r3.py::test_source_binding_carries_configured_quote_scope_and_proposal_sources`: `market_snapshot READY universe quote coverage incomplete`.
  - `tests/manager_workbench/engines/test_us_mapping.py::test_v3_48_symbol_scope_and_proposed_relations_remain_observation_only`: actual reason `US_SESSION_RELATION_OR_CONNECT_UNVERIFIED` differs from expected `US_RELATION_PROPOSED_PIT_UNCONFIRMED`.
  - `tests/manager_workbench/engines/test_us_mapping.py::test_unknown_universe_version_is_rejected_as_unassessed`: expected `US_UNIVERSE_CONTRACT_VERSION_UNSUPPORTED` gap is absent.
- The explicitly deselected case, `tests/test_runtime_dispatcher.py::test_real_catalog_dispatches_single_intraday_cli_and_binds_release`, imports `test_v4_intraday_research.fixture_config` and executes the separate 11:30 intraday workload. Its helper and the wider intraday source closure are outside this four-breakpoint export. It is `NOT_RUN_OUT_OF_SCOPE`, not a behavior failure. No test file was edited to hide it.
- Requirements parse and resolve in a non-mutating offline dry-run: `uv pip install --dry-run --offline --no-index --python .venv/bin/python -r docs/handoffs/us_hk_source_baseline_20261018/DEPENDENCY_MANIFEST.txt` → `Checked 9 packages; Would make no changes.` The workspace venv lacks the `pip` module, so `.venv/bin/python -m pip ...` could not run; no dependency installation was attempted.
- The original export security scan found no high-confidence credential-pattern matches. A follow-up scan of the two refreshed files also found no AWS, GitHub, OpenAI, private-key, or Slack token-pattern matches. Raw quote/mapping inputs, the 43,652,024-byte full recovery overlay, credentials, runtime release files, logs, and backups were not exported.

## Runtime and source boundary

The manifest source is the dirty canonical worktree at `HEAD=55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`; it is not proof of target GitHub base correspondence. The controller owns branch selection and GitHub sync. The actual runtime roots reflected in this baseline are:

- US digest `us-entry-count-repair-20261017-r1/app`; four release-identity environment keys are bound. This supersedes the prior packet's missing-identity premise; current manifest-check/dispatch success remains `CANNOT_CONFIRM`.
- Manager scheduler `zsxq-long-pdf-scheduler-20261016-r3/app`.
- Selector API `us-receipt-compat-api-20261017-r1/app`, selected via `ProgramArguments`/`V35_APP_ROOT`, overriding the old `r11c` environment value.

The per-file SHA differences are in `SOURCE_EXPORT_MANIFEST.json`. The baseline export is mirrored to canonical repository paths on the controller-published branch. The local `staging/` tree is excluded from the remote branch and does not need to be read; it is retained on the source machine as a provenance cache. This writer did not alter release copies or services. The four Issue 45 behavior statuses were not revalidated here; exact-date handoff, full owner-overlay selector readback, API/page reload, notification, and natural-slot output remain `CANNOT_CONFIRM`.

## Reproduction commands

Dependency dry-run:

```sh
uv pip install --dry-run --offline --no-index --python .venv/bin/python \
  -r docs/handoffs/us_hk_source_baseline_20261018/DEPENDENCY_MANIFEST.txt
```

The historical focused-suite command ran from an isolated copy of local-only `staging/` with a fresh pytest temp directory. The remote branch intentionally excludes `staging/`; reproduce the same test selection from a clean checkout's repository root against the canonical source paths:

```sh
env -u PYTHONPATH -u PYTHONHOME /Users/lexi/Desktop/学习/v4_app/.venv/bin/python -m pytest \
  -q --tb=short --basetemp=/tmp/v4-issue45-baseline-final-test -p no:cacheprovider \
  tests/test_run_us_market_slot.py tests/test_runtime_dispatcher.py \
  tests/test_us_owner_handoff.py tests/test_us_equity_calendar.py \
  tests/test_manager_us_market_bridge.py tests/test_manager_us_mapping_bindings_r3.py \
  tests/manager_workbench/test_oversold_daily_scheduler.py \
  tests/manager_workbench/engines/test_us_mapping.py \
  -k 'not real_catalog_dispatches_single_intraday_cli_and_binds_release'
```

The earlier import smoke used an inline Python check from the isolated staging cwd. It imported the ten module names listed above, asserted every `module.__file__` was below that cwd, asserted the canonical source root did not appear in `sys.path` (except under `.venv`), then printed `ISOLATED_IMPORTS_PASS`. It was not rerun after the final file refresh.

## Files and remaining ownership

Files created or populated by this writer are limited to:

- `SCOPE.md`
- `SOURCE_EXPORT_MANIFEST.json`
- `DEPENDENCY_MANIFEST.txt`
- `README.md`
- `REMOTE_ROOT_README.md`
- `UPDATED_CHAT_PROMPT.md`
- this `WRITER_RECEIPT.md`
- `staging/**` local-only complete source/test dependency closure and two fixtures; excluded from the remote GitHub branch

The controller retains `ROOT_DELIVERY.md`, `ROOT_LEDGER.json`, and `GITHUB_SYNC_RECEIPT.json`. The independent reviewer owns `INDEPENDENT_REVIEW.md/json`. GitHub sync, target branch correspondence, final clean-copy reviewer verdict, business repair, deployment, API/UI, notifications, and natural-slot validation remain outstanding or `CANNOT_CONFIRM` as appropriate.
