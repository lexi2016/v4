# Exact manager run / terminal / latest implementation report

Fixed target: `f7cb731c384ee6890a87d16c19a5b5a621779477`.
Runtime actually used: `work/V5/.venv/bin/python`, Python 3.14.6, original frozen uv.lock dependencies.

## Changed behavior and code scope

`V5/src/v5_shadow/manager_plan.py::_assemble` now binds an exact returned product to the original store reader without modifying the pinned owner. The existing `plan_store()` accepts a strictly validated 32-lowercase-hex run selector; only the specific target's `workspace_plans/<target>/latest.json` read is redirected to the same directory's `<run>.json`. The real store and original `_read_plan` still validate schema, target dates, owner, all safety flags, complete SHA, workspace/input identity, generated time and execution kind. The requested run is separately compared to the row run. Source and journal paths are unchanged.

Refresh uses the exact returned product plus its original `verified_plan_attempt` same-run terminal. Missing or borrowed terminal cannot produce `MATCHED`. The response terminal and native daily channels are rebound to that verified exact attempt if the returning owner snapshot contained another journal.

`readback.latest_observation` is independent. It records observation time, observed run/product SHA, and `VERIFIED` / `MISSING` / `CANNOT_CONFIRM`. `VERIFIED` requires that observed run's own exact product and own terminal. `matches_exact_run` is true or false only after that verification and null when unconfirmed. A missing or damaged latest, or a different latest whose terminal is missing, cannot undo exact A's completed readback. Different run does not imply later time or completed business acceptance. This diagnostic verifies stored owner contracts; it does not replay another request's business sources or confer natural/production qualification.

Ordinary nonhistorical reads retain the original owner source replay. When the consumed product is A but the independently observed latest journal is B, the adapter validates A's exact product and terminal again, uses A for `workspace_plan_attempt`, and runs the original `build_daily_channels` if that displayed attempt changes. The original B journal remains in `readback.latest_attempt_observation`, explicitly scoped as an independent latest-journal observation. This does not modify saved product bytes or their SHA, plan context, source identity, dates, stocks or admission rules.

### Approved terminal-contract tightening

The original owner permits a MANUAL_REFRESH product without an exact journal and treats it as legacy. The former test named `test_same_day_manual_legacy_missing_journal_keeps_original_compatibility` actually created a fresh current owner product and then deleted its journals; it proved `CURRENT/consumed=True` with no exact terminal. The main agent approved tightening this V5 ordinary-read behavior to satisfy the module prompt.

Such a same-day product now remains visible by run/SHA as `OWNER_ATTEMPT_UNVERIFIED`, `consumed=False`, reason `MANAGER_EXACT_OWNER_ATTEMPT_MISSING`. The adapter obtains the original owners' fresh read-only preview with `include_saved=False`; healthy source projections remain available, while manager-execution channel references are unverified. The exact missing-terminal test checks preview stocks, materials, announcement analysis, input identity, and unchanged output bytes. `CURRENT_RECOVERY` already rejected missing exact journals and keeps its existing reason/gates. Explicit historical replay is unchanged.

Changed test scope was explicitly extended by the main agent to that one case in `V5/tests/test_manager_current_recovery.py`; it was renamed to the new behavior and its assertions strengthened. The old failing assertion output was preserved before editing it.

`V5/src/v5_shadow/manager_plan_io.py` and all vendor/contract manifests remain byte-identical to the fixed target. No new persistent store, operation id, HTTP POST, network production call, raw business data or credentials were introduced. The main agent is separately modifying the existing publication helper/tool after this file's body was frozen.

## Behavioral verification

New tests are `V5/tests/test_module01_exact_run.py`. They load the actual pinned owner and original SafeRoot in isolated temporary roots. Refresh A and B both really execute and persist. The ordinary-read race uses two real processes: pause the reader immediately after original `_read_plan` reads A, run real B to completion, then resume A's reader before it reads the latest journal. Corruption seams alter only isolated test outputs after real owner completion. Empty owner inputs are clearly synthetic and provide no market/business acceptance evidence.

| Raw log | Actual result |
| --- | --- |
| `logs/exact_run-red.log` | Original 12-test RED: 7 failures and 1 missing-new-field KeyError; no production edit yet. The assertion was corrected and this log retained. |
| `logs/exact_run-red-behavior.log` | Original 12-test RED: 8 intended behavior failures, 0 errors, 11.058s. |
| `logs/exact_run-green.log` | Initial 12 tests pass, 10.069s. |
| `logs/exact_run-regression-plan.log` | Original manager-plan/date-gate regressions: 8 pass, 8.423s. |
| `logs/exact_run-regression-recovery.log` | Original CURRENT_RECOVERY regressions before approved terminal tightening: 16 pass, 22.495s. |
| `logs/exact_run-red-terminal-gaps.log` | Added same-day missing-terminal and late-returned-journal cases: 14 tests, 2 intended failures, 13.901s. |
| `logs/exact_run-green-terminal-gaps.log` | All 14 exact-run tests pass after tightening, 14.081s. |
| `logs/exact_run-old-compatibility-after.log` | Original CURRENT_RECOVERY suite after tightening: 15 pass, the one superseded legacy-consumption assertion fails, 21.725s. This failure was preserved before editing that approved test. |
| `logs/exact_run-green-new-manual-contract.log` | Approved renamed missing-journal test passes, 2.202s. |

Commands used: `.venv/bin/python -m unittest discover -s tests -p 'test_module01_exact_run.py' -v`; analogous discovery of `test_manager_plan*.py` and `test_manager_current_recovery.py`; final focused discovery adds `-k 'same_day_manual_missing_journal'`. Every command used `set -o pipefail` and retained raw output with tee. `git diff --check` exited 0.

Full project suite and publication/browser verification are coordinated by the main agent after all candidate files freeze. No complete-project success claim is made by these scoped results. Mac real 392 originals, real active API and built-in browser acceptance are NOT_RUN here. Natural-period and three-lane business acceptance remain unchanged.

## SOURCE_TARGET_MAP row suggestions

| Donor semantics | Actual V5 target | Existing equivalence / action |
| --- | --- | --- |
| FOUR router post-save independent readback and A `_read_plan` / `verified_plan_attempt` | `src/v5_shadow/manager_plan.py::_assemble`, exact `plan_store` transport | Needed: original V5 independent readback read latest. Reuse the actual V5 pinned validators through a bounded exact-file transport; do not transplant FOUR router or A workspace. |
| A same-run terminal ownership / store-safe file access | `vendor/manager_plan_baseline/v4/manager_research/workspace.py::verified_plan_attempt`; `src/v5_shadow/manager_plan_io.py::allowed_file` | Already equivalent, retain bytes. V5 adapter now requires actual terminal for refresh and nonhistorical consumed display. |
| F02 independent exact-versus-latest reporting | `src/v5_shadow/manager_plan.py::_assemble::latest_observation` | Needed: observed latest has its own exact product and terminal verification; unavailable observation does not fail completed exact run. |
| A native ordinary read product/terminal pairing | `src/v5_shadow/manager_plan.py` read branch / `bind_plan_attempt` | Needed: pinned owner returned latest journal beside earlier product in a real interleaving. Adapt only after original source and exact owner checks, then rebuild original native daily channels. |
| A historical exact-file/source/PIT replay | `vendor/manager_plan_baseline/v4/manager_research/workspace_history.py::_read_candidate`, `select_plan`, `read_history`; V5 `_plan_store_scope` | Already retains exact filename binding, source replay, PIT, cutoff and CURRENT_RECOVERY separation. Keep bytes and historical behavior. |
| Existing MANUAL_REFRESH no-journal compatibility | `src/v5_shadow/manager_plan.py` nonhistorical read; one existing CURRENT_RECOVERY test | Approved contract tightening: expose unverified saved reference plus original fresh preview; never borrow latest journal or claim consumed without exact terminal. |

## Frozen subtask hashes

These hashes precede the main agent's separate publication helper change in the same module; packaging must recompute final combined SHA.

- `manager_plan.py`: `7827c5fd83f2fbbfc021a91cae696703ac39df6517671a8442eb223fd017abe1`.
- New `test_module01_exact_run.py`: `937ba79f3dfce666564da44f8f477d4937d314db1beac49a2c2e2b2a1d35d284`.
- Modified `test_manager_current_recovery.py`: `6f77e52e5fab25c1ea6a0cc523d6fbc7b8fd997703ccd33999a735253bd51a71`.
- Unchanged `manager_plan_io.py`: `55188270be31f27fe1169e4aae1cc7e9a0e1db87b11b780d2e0778060b0572cb`.
