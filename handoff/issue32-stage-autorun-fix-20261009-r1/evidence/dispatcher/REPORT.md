# Issue32 scheduler source delta

## Finding and scope

The supplied actual dispatcher does not contain an upstream readiness preflight. It calendar-selects due workloads and invokes the executor. `UPSTREAM_NOT_READY` is a failure class inferred from executor results. The historical `started_workload_ids` field is populated only on successful completion, so `[]` does **not**, by itself, prove no executor or producer was invoked. The exact cause of the 2026-10-08 17:30/18:00 failure remains **CANNOT_CONFIRM** without those full receipts and the actual facade/configuration.

The reproducible defects in the supplied handler are separate: it invoked HK scoring after price update or security-master preparation failed; a successful local materializer could then allow the required HK failure to settle the whole dispatch as successful. These are directly covered by the RED tests.

## Changes

- Both dispatchers retain the legacy `started_workload_ids` semantics and add `invoked_workload_ids` and `succeeded_workload_ids`. No claim, calendar, slot, release-identity, or manager-capture gate changes.
- Actual legacy preselection and canonical split helper require successful original-owner price update and security-master preparation before HK scoring.
- They pass `--prepare-exact-date` to the paired new `ops.ensure_hk_security_master` implementation. That flag is intentionally incompatible with the old preparer; deploy the pair together. Historical source roots are never guessed. The HK preparer owns the verified-restore and same-day acquisition implementation and tests.
- A/local materialization still runs. Missing optional A/D1 enrichment remains nonblocking. Required HK failure is returned through the existing `FAILED`/typed failure contract with `first_gate`, original lane errors, and `materializer_status`. Both handlers retain success when the authoritative local HK gate independently verifies an already-valid pool; actual absence is allowed only through the existing verified formal-pair reuse contract.
- Existing failure classes are retained; blank classes receive the HK child class or `UPSTREAM_NOT_READY`. Existing dispatcher retry-after and failed-claim release mechanisms are reused. No historical settled slot is reset, rewritten, deleted, or reclaimed by this patch.

## Test evidence

From `issue32/`:

```bash
PYTHONDONTWRITEBYTECODE=1 ISSUE32_SCHEDULER_SOURCE_ROOT="$PWD/input/baseline" /workspace/scratch/25c09a595aec/issue28/references/work/test-venv/bin/python -m pytest -q tests/test_dispatcher_receipts.py tests/test_preselection_executor_prerequisites.py --tb=short
PYTHONDONTWRITEBYTECODE=1 /workspace/scratch/25c09a595aec/issue28/references/work/test-venv/bin/python -m pytest -q tests/test_dispatcher_receipts.py tests/test_preselection_executor_prerequisites.py --tb=short
```

Initial RED: **12 failed, 4 passed** (`red.log`); paired-flag RED: **2 failed** (`prepare_contract_red.log`); additional blank-failure-class RED: **2 failed, 2 passed** (`failure_class_red.log`). Initial GREEN: **22 passed** (`green.log`). Independent review then reproduced a second settlement defect: successful HK scoring could hide an explicitly rejected local HK pool. New review RED: **27 failed, 3 passed** (`local_gate_red.log`). Final scheduler plus independent review GREEN: **52 passed in 0.27s** (`local_gate_green.log`), comprising 50 scheduler tests and two independent review probes. The first two RED invocations preceded all production changes; the additional RED tested the next corrective edit. Original run commands did not set `PYTHONDONTWRITEBYTECODE`; final GREEN does. The shown baseline rerun now includes the subsequently added tests, so its count differs from the initial RED log.

These tests load the supplied production slice but explicitly stub missing import and subprocess boundaries in `scheduler_slice_harness.py`. They prove control flow and receipt construction, **not** the current facade, real ledger, a financial artifact, market-calendar resolution, release identity, current Mac runtime, deployment, API/UI, or natural slots. No source snapshots were relabeled as the active application. Full active-app and natural-slot validation: **NOT_RUN**.

## Independent review: local HK gate is decisive

The final handler changes also close the successful-scorer path. An eligible canonical HK lane must have its known parsed `formal_pool_gate.required.hkconnect_d1_top100.ready` literally equal to `True`; false, absent, malformed, numeric `1`, or string `"true"` cannot settle success. The first failure is `HK_LOCAL_POOL` after successful upstream work, or the earlier preparation gate if that already failed. Noneligible HK remains nonblocking.

The actual facade/materializer schema is still absent from the handoff. The actual patch therefore does **not** invent a stdout decoder or label subprocess exit 0 as local readiness. It consumes only an existing `_authoritative_payload` dictionary containing the same literal mapping. An explicit rejected or malformed gate fails with `HK_LOCAL_POOL`. Absent authoritative gate/no already-verified formal pair fails with `HK_LOCAL_POOL_CONTRACT_UNAVAILABLE`; an earlier prep failure remains the first gate. Original child status is preserved in `materializer_status`, and A/local materialization has already run. Existing verified formal-pair reuse is the only gate-absence exception, and cannot override an explicit local rejection.

**Compatibility status: BLOCKED / MISSING_CURRENT_INPUTS.** Whether the actual current materializer and `_run` populate that authoritative field is unknown. Supply their exact bytes and run the current-owner Mac canary before claiming readiness. If they do not emit the verified gate and no existing verified pair exists, this candidate deliberately reports the missing contract. Do not synthesize a gate, substitute canonical parser behavior, or remove this fail-closed condition. The original Stage's independent A artifact consumption must also be checked on Mac; it must not reinterpret the aggregate HK failure as loss of valid A inputs.

The final focused command, run from `issue32/`, was:

```bash
PYTHONDONTWRITEBYTECODE=1 /workspace/scratch/25c09a595aec/issue28/references/work/test-venv/bin/python -m pytest -q tests/test_dispatcher_receipts.py tests/test_preselection_executor_prerequisites.py tests/test_preselection_executor_local_gate.py evidence/independent_review/test_local_hk_gate_review.py --tb=short
```

`tests/scheduler_slice_harness.py` now matches the provided canonical facade's literal JSON-object decoder for the canonical tests. The actual test path uses only the existing authoritative payload boundary. These synthetic boundaries do not attest to the missing actual runtime interface.

## Required current-owner closure and readback

- Actual release `20260929-manager-1555-pytdx-r1`: `infrastructure/scheduling/executor_registry.py` and any helpers it rebinds, especially process-result parsing and failure construction; `execution_ledger.py`; `contracts/runtime_tasks.py`; `contracts/trading_calendar.py` and actual calendar data; `domains/runtime_policy.py`.
- Actual runtime catalog (`contracts/runtime_workloads.json`) and scheduled-slot/scheduler launch entrypoints, effective configured source roots, executable identities, relevant sanitized environment and schedule configuration.
- Full 17:30 and 18:00 receipts, particularly `workload_results`, stderr/stdout, failure class, release ID, request dates, and selected/invoked producer details. Supplied receipt SHA references alone cannot establish which gate failed.
- Original owner price updater, acquisition entrypoint, isolated package loader, universe resolver/authority, scheduled materializer, pool readers/writers and their exact versions. The full HK dependency list is owned by the HK preparer report.
- Canonical split `_namespace.py`, process-boundary helper, and release-identity file closure must be supplied for integrated canonical tests; the canonical reference is not a whole-file replacement for the legacy executor.

The historical canonical ledger downloaded by the root agent documents FAILED-only claim release and successful-claim retention, but its bytes are **not attested as the current actual ledger** and were not used to claim deployed retry behavior.

## Mac handoff

Verify source paths and before hashes in `SOURCE_DELTA.json`, then apply each owner-specific hunk to its matching version. Install the actual executor/preparer pair together with the HK owner delta; retain canonical changes only in their canonical paths. Run the original facade, real ledger, exact-source preparation, and isolated Stage canary on Mac. Before allowing any retry, inspect the latest current receipt and original retry schedule; do not delete or reset old terminal slots. Preserve all three false safety flags. If the required 10/8 verified source is absent, return the new explicit blocked reason, not target-day success.
