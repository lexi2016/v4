# Issue #35 / 20261012 — owner dispatch stale-read failure recovery (additive R2)

**Deliverable: real, applyable single-file hunk + offline regression. NOT DEPLOYED.**
Parent source: `codex/issue35-autocontinue-fix-20261011` at
`37de6a9970eb9be05a79c5be0e2e5a39bddd6426`.
Original owner chain/three-mode patches remain in
`handoff/issue35-autocontinue-fix-20261011/`; this additive patch does not
supersede its canonical/runtime variants, bind a Mac scheduler, or create a producer.

## Reproduced blocker and fix

The previous `_completed_dispatch_still_current()` validated only the original
terminal attempt inside a try block, **but called both the sealed latest-plan
reader and the live workspace reader outside** that block. Controlled
`ValueError` / `WorkspaceReadError` during either validation escaped
`_execute_serialized_cycle` *before* a new
RUNNING→terminal dispatch receipt was written. This breaks the required
same-trigger failure/recovery chain. For an unverifiable re-read, the owner must
**not replay** the old completed receipt; the existing `_run_owner_branches`
and its bounded retry/receipt logic must decide the outcome.

`patches/dispatch_after_issue35_failure_recovery.patch` moves
`_read_plan`, exact-run attempt and `get_workspace(... include_saved=True)`
into a single bounded owner error guard and catches original
`workspace._ERROR_TYPES` (including `WorkspaceReadError` and `TimeoutError`).
Any unreadable sealed plan or current workspace
returns `False` for *replay eligibility*, not `SUCCEEDED` and not a fabricated
empty selection. Actual new owner execution may still fail accurately and
remain unfinished. No strategy, date/PIT, security, scheduler, UI, order or BUY
code is altered.

## Strict application order on Mac — isolated candidate only

1. Select **one** matching source mode from the parent handoff:
   `canonical_r2`, `runtime_r1`, or `runtime_after_r2`. Apply its owner
   workspace + dispatch + required Stage service/app patches using the parent's
   SHA-checked `scripts/check_or_apply.py`; **never combine source modes or
   overwrite the canonical working tree**.
2. On the resulting isolated application root (NOT the active 8873 root):

```bash
APP=/path/to/isolated/candidate/app
HANDOFF=/path/to/repo/handoff/issue35-autocontinue-failclosed-20261012-r1
test "$(shasum -a 256 "$APP/v4/manager_research/plan_owner_dispatch.py" | cut -d' ' -f1)" = "8afc3439070f8ea71b112a51c154775d7eb948c60082ca032f05d9771a34b284"
cd "$APP"
git apply --check "$HANDOFF/patches/dispatch_after_issue35_failure_recovery.patch"
git apply "$HANDOFF/patches/dispatch_after_issue35_failure_recovery.patch"
test "$(shasum -a 256 v4/manager_research/plan_owner_dispatch.py | cut -d' ' -f1)" = "b782d8a7d18c6d5a2a6ace9612761de9fb22b45eb544cdd33145429b00e165c8"
ISSUE35_APP_ROOT="$APP" python3 -m unittest discover -s "$HANDOFF/tests" -p 'test_*.py' -v
```

If either SHA assertion fails, STOP and request a targeted three-way hunk merge;
do not force `git apply`, replace whole files, or deploy. Bind against Mac's
loaded code inventory and owner data roots, retain the old HK scheduler and
original announcement collection job(s), then use the original rollback/CAS
activation; this patch does not sign a new binding.

## Verified independent offline evidence

The source SHA `8afc...b284` was reconstructed byte-for-byte by applying the
upstream `runtime_r1` patch to SHA `d167...d97`. This additive patch was
then actually applied via `git apply --check` + `git apply` to the matching
isolated source, producing exact `b782...5c8`. `py_compile` passed. Ten
isolated synthetic *actual AST function body* exercises: **10/10 PASS** after
fix. Before fix, the controlled stale-read failure test threw
`ValueError: SYNTHETIC_OWNER_READ_FAILED`; after fix, replay eligibility
became false and the existing dispatch appended a new owner receipt. Added a
corrupt saved-latest-plan read failure injection with the same behavior. Other
scenarios: same input one run, changed identity new run, sealed readback order,
old latest restored after post-terminal failure, missing-input PARTIAL retained,
old dispatch receipt immutable. These use fake store/inputs and are NOT full
application imports or real Mac business-data evidence.

The included shorter test `tests/test_failclosed_dispatch.py` is runnable on
the isolated candidate and explicitly does not need Mac market data. Real
`pytest`/calendar/owner integration and independent Mac Reviewer remain due.

## Target-day data and execution NOT established here

20261012 still requires separately validated original owner products:公告
20261009 catalog 383/21, original body 319 complete / 64 capture failures,
semantic review and product import NOT_VERIFIED; 超跌 60+5 historic panel,
TDX volume unit, original screen run/product NOT_VERIFIED; US
20261009 raw 18 sectors/23 individuals READY but daily owner 20261012
NOT_RUN and formal HK mapping list unverified. Old 10/09 55公告/214超跌
are not 10/12 selected stocks. Actual input change may also require
another legitimate trigger within original retry/window budget. The original
Manager binding, natural scheduler slot, 8873 API, page reload and three
lists are **NOT_RUN / CANNOT_CONFIRM** in this cloud environment.

Acceptance remains **OPEN**. RESEARCH_ONLY=true, production_allowed=false,
buy_gate_updated=false, orders_sent=false. No trading APIs called.
