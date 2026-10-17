# Issue 45 complete source baseline

This handoff records the complete Issue 45 source and focused-test dependency closure. The local verification copies live under `staging/<repository-relative-path>` on the source machine only; `staging/` is excluded from the remote branch and Chat does not need to read it. The remote checkout contains the formal source files at their canonical repository paths. This is a source baseline, not a code repair or proof that any live layer accepted the result.

## Contents and provenance

`SOURCE_EXPORT_MANIFEST.json` maps every local staged file to its original repository-relative path (or, for the two fixtures, its prior packet path), sampled source SHA-256, staged SHA-256, and byte size. It also records the observed runtime roots and per-file comparisons for the core entry modules. The export contains 436 regular files totaling 8,361,532 bytes: 434 canonical-worktree source copies and two derived test fixtures from the prior handoff. During reconciliation, `v4/manager_workbench/api.py` was refreshed after its 24-line cached-recovery route addition, and `v4/manager_workbench/announcement_update.py` was refreshed to include the route's `start_cached_product_recovery` dependency. Both import sets were unchanged, with no new module dependencies. The final source snapshot was frozen at `2026-10-18T00:40:31.612+08:00`; later canonical drift is outside this snapshot and is not pursued. A relative `staging/v3_shared_data -> upstreams/v3_shared_data` symlink stays within the local export. All staged SHA/size entries match the manifest, and the high-confidence credential-pattern scan found no matches in the two refreshed files.

The fixture `staging/tests/fixtures/issue45/real_relation_projection.json` is the 1,003-relation, quote-free derived projection from the prior packet. It is not an owner artifact and not the full recovery overlay. `synthetic_contract_fixture.json` is a small contract test fixture. The full 43,652,024-byte recovery overlay, raw quote capture, raw mapping input, account data, and credentials are excluded.

The canonical source snapshot came from the dirty worktree at `HEAD=55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`; the source files are not all present at that commit. The controller has published the complete necessary files at their canonical repository-relative paths on the handoff branch. `staging/` exists only on the source machine and is not included remotely; Chat should edit the formal source files in the clean GitHub checkout and run tests from the repository root. Do not look for, copy, or reapply `staging/` in that checkout.

## Runtime identity update

The previous packet describes an older runtime state. The current handoff scope records these newer roots:

- US digest: `us-entry-count-repair-20261017-r1/app`; the four release-identity environment keys are bound. This changes the old “identity variables absent” premise, but does not prove a current dispatch or manifest check succeeded.
- Manager scheduler: `zsxq-long-pdf-scheduler-20261016-r3/app` remains the selected source root.
- Selector API: `us-receipt-compat-api-20261017-r1/app` is selected through `ProgramArguments`/`V35_APP_ROOT`, overriding the older `r11c` value in `EnvironmentVariables`.

The manifest records exact SHA comparisons for relevant files. Old failure statements in `us_hk_friday_close_20261017/packet/CHAT_ISSUE.md` are historical evidence; re-check them against the target source and current receipts. `RELEASE_IDENTITY` success, exact date mapping, post-close consumer refresh, full overlay readback, API/page reload, notification, and natural-slot behavior remain `CANNOT_CONFIRM` here.

## Reproducing imports and focused tests

Use Python 3.14 and install the direct pinned requirements from the handoff root. A pip-enabled environment can use:

```sh
python -m pip install -r docs/handoffs/us_hk_source_baseline_20261018/DEPENDENCY_MANIFEST.txt
```

The current workspace venv has no `pip` module; its non-mutating dependency check used `uv pip install --dry-run --offline --no-index --python .venv/bin/python -r docs/handoffs/us_hk_source_baseline_20261018/DEPENDENCY_MANIFEST.txt` and resolved all nine requirements without changes. Run that same requirements path from any clean checkout.

The Writer's recorded isolated run used a private copy of the local-only `staging/` export. In the remote GitHub checkout, reproduce the focused test selection from the repository root against the canonical paths, with both `PYTHONPATH` and `PYTHONHOME` unset:

```sh
env -u PYTHONPATH -u PYTHONHOME python -m pytest -q --tb=short \
  tests/test_run_us_market_slot.py \
  tests/test_runtime_dispatcher.py \
  tests/test_us_owner_handoff.py \
  tests/test_us_equity_calendar.py \
  tests/test_manager_us_market_bridge.py \
  tests/test_manager_us_mapping_bindings_r3.py \
  tests/manager_workbench/test_oversold_daily_scheduler.py \
  tests/manager_workbench/engines/test_us_mapping.py \
  -k 'not real_catalog_dispatches_single_intraday_cli_and_binds_release'
```

For fully isolated pytest temporary files, add `--basetemp=/tmp/<new-unique-path>`. The excluded dispatcher case imports `test_v4_intraday_research.fixture_config` and executes `ops.run_intraday_research` for a separate 11:30 intraday workload; neither that helper nor the unrelated intraday runner closure is part of this bounded Issue 45 export. The test was excluded explicitly, not edited or masked. Do not interpret this focused baseline suite as complete application acceptance.

Only the Writer's local provenance check compares every `staging/<path>` SHA with `source_sha256` in the manifest. The remote checkout already contains the full canonical files at their formal paths; continue implementation there without looking for or copying the local cache. `REMOTE_ROOT_README.md` is the compact remote repository entry page for this baseline.

## Baseline test status and limits

The earlier isolated focused suite returned 225 passed, 3 failed, and 1 explicitly deselected. The same three failures reproduced on the then-current canonical worktree with the same assertions: one `READY` market-snapshot fixture failed quote-coverage validation; two mapping-engine expectations differed on an unverified-relation reason and unsupported-universe gap. They are preserved as existing source/test mismatches, not repaired in a source-baseline task. The deselected intraday dispatcher case is documented above and is not counted as a behavior failure. The API and announcement-update files were refreshed after that run to freeze their complete current source dependency; the final frozen snapshot suite was not rerun and remains `CANNOT_CONFIRM` pending the independent reviewer.

This export does not modify the four business breakpoints. It does not verify an official US daily close, a canonical owner artifact, complete-overlay runtime consumption, API/page state, notification, or a natural slot. Keep the research-only/trading flags and relation status boundaries described in the prior issue unchanged.
