> 本文保留初次跨日修复阶段的计划/证据。独立审查后追加的 exact journal 缺失拒绝及最终整合结果，以交付根 README.md、VALIDATION.md、CHANGE_MANIFEST.json 为准；本文旧测试数量不是最终总数。

# Current recovery result and reproducible verification

## Result

The fixed `20261009` revision fixture now saves and reads through ordinary
`view=auto` with the same original-owner run and plan SHA, using the actual later
clock. Successful recovery is explicitly `CURRENT_RECOVERY`; its read context
states `historical_eligible=false`, `owner_view=dynamic`, and the requested view.
The original workspace/attempt verification still decides whether the plan is
consumed. Changed inputs and invalid attempts keep the original rejection status.

Only `src/v5_shadow/manager_plan.py` changes production behavior. The frozen
manager owner, its history module, source descriptor, I/O guards, and all original
BUY/Stage/market admission logic remain byte identical. The comparison found zero
changes among 447 vendor files and 17 contract files.

## Storage and API contract

Past-target refreshes write an independent original-owner store at
`<manager_output_root>/current_recovery`. The original plan and attempt formats
are retained under its `workspace_plans/<date>` and `workspace_plan_runs/<date>`.
`readback.store_relative` is `current_recovery` for that store and `.` for the
original store. The tests and the existing private-owner acceptance locator use
this explicit field.

Ordinary auto or dynamic reads use the recovery store only if its exact target
has a committed `latest.json`. A recovery for another target cannot select it.
Explicit history always reads the original store and retains its original
pre-session cutoff and PIT qualification. Recovery files are not migrated into
that store. A pre-fix late plan in the original store is not silently promoted;
an explicit refresh is required to create a new recovery with its real cutoff.

The recovery identity is a response discriminator. It does not rewrite a saved
plan or rehash it, and its native owner status is retained as `owner_status`.
The original already-validated channel execution references stay attached with
an explicit current-recovery scope. Formal stock/admission results do not change.

The same-day request route retains the original store and `CURRENT` behavior.
The adapter rejects future `now` using its existing `MANAGER_FUTURE_CUTOFF` gate;
future target dates retain the native next-session planning semantics.

## Executed evidence

`evidence/current_recovery/RED.log` records the first CPython 3.14.6 run before the
production change: four tests, three expected assertion failures and one pass.
Both ordinary readback cases returned no saved run, and removing the admitted
revision returned `NOT_MATERIALIZED` instead of the required stale-input result.

`FIRST_GREEN_ATTEMPT.log` records the complete first run after the code change.
All thirteen new recovery cases and three revision-chain cases passed. Three
existing manager tests still expected the old physical path or `CURRENT` label;
their locators/expectations were updated for the new contract, while their SHA,
same-attempt and saved-context assertions were retained. The private real-owner
test received only its matching path-locator update.

`GREEN.log` records the final focused command with exit code zero: **65 tests,
65 passed**, consisting of thirteen new recovery cases, three fixed revision
chain cases, six existing manager adapter cases, and all original forty-three
daily/ledger/scope cases. There were no skipped tests in this command.

Runtime: Linux x86_64, CPython 3.14.6, NumPy 2.5.3, pandas 2.3.3, PyArrow 24.0.0.
The environment was installed by the parent task from the original `uv.lock`
with `--locked --no-install-project`; `PYTHONPATH` selects the isolated candidate.
An earlier unchanged-source CPython 3.12.14 mechanism probe also reproduced the
original chain failure, but is not used as the final runtime acceptance.

The passing cases establish same-day behavior; cross-day same run/SHA; actual
generated time and cutoff; unchanged original plan bytes including old pointers;
missing-history and exact-target gates; repeated reads with no writes; invalid
attempt refusal; admitted revision removal becoming stale; changed byte-pin
refusal; future-clock refusal; symlink refusal; and ordinary loopback HTTP GET
serving the same committed recovery response under the `view=auto` query.

## Reproduce

In this workspace the exact interpreter is
`/workspace/scratch/17ec887ca39d/runtime/v5-env/bin/python`, the candidate V5 root
is `/workspace/scratch/17ec887ca39d/work/crossday/V5`, and the fixed e06d fixture is
`/workspace/scratch/17ec887ca39d/input/sources/e06d/bundle`.

From the candidate V5 directory, use the same command on a separately prepared
locked CPython 3.14.6 environment:

```sh
export PYTHONPATH=src:tests
export V5_ANNOUNCEMENT_REVISION_TEST_BUNDLE=/ABS/FIXED_E06D_BUNDLE
/ABS/LOCKED_ENV/bin/python -B -m unittest \
  test_manager_current_recovery test_daily_revision_chain test_manager_plan \
  test_us_mapping_scope test_run_ledger test_daily_dispatch test_daily_us_owner \
  test_daily_owner_adapters test_daily_manager_assembly -v
```

To repeat the original RED against unchanged source, select the original source
and candidate test directories explicitly:

```sh
export PYTHONPATH=/ABS/ORIGINAL_3D9541AC/V5/src:/ABS/CANDIDATE/V5/tests
export V5_ANNOUNCEMENT_REVISION_TEST_BUNDLE=/ABS/FIXED_E06D_BUNDLE
/ABS/LOCKED_ENV/bin/python -B -m unittest \
  test_manager_current_recovery.ManagerCurrentRecoveryTests.test_crossday_refresh_and_auto_read_keep_same_run_and_sha \
  test_daily_revision_chain -v
```

## Remaining acceptance

The parent task will execute full project discovery after combining the manager
and interface deltas and report every fixture/platform failure or skip. This
focused run does not stand in for that integrated suite.

Mac private-asset acceptance and the deployed API/Chrome page remain **NOT_RUN**.
`test_manager_announcement_binding.ManagerAnnouncementRealOwnerTests` is also
**NOT_RUN** here because its existing private request/758-file fixture is absent.
The loopback HTTP test is a real local server/client test with synthetic inputs;
it is not a claim about a deployed service or a browser session. The fixed e06d
chain uses explicitly synthetic article inputs and does not invent a private
392-article review, reviewed decision file, PASS, real recovery, or natural run.

No GitHub push, deployment, V4 modification, source recapture or private-owner
mutation was performed by this subtask. Per-file provenance and SHA comparisons
do not claim the unavailable binary ZIP itself was downloaded and verified.
