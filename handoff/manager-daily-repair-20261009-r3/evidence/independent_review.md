# R3 independent read-only code review

## Scope and status

Reviewer: independent `r3_final_review` agent. The reviewed contract is
`v4-input/handoff/manager-daily-failure-20261009-r3/package/CHAT_TASK.md`.
The comparison base is `r3-work/baseline` (cumulative R1/R2), and the proposed
changes are in `r3-work/candidate`. No production source file was edited by
this reviewer. Only this evidence directory is written; all executable probes
use temporary synthetic source roots and temporary stores.

**Final review: the three initial findings are closed after independent
reproduction and fresh verification. No remaining P1/P2 was found within the
reviewed R3 contracts.** The unchanged inherited test failure described below
remains. This conclusion covers the supplied code/test closure; it is not a
full-runtime or Mac deployment acceptance.

Initial review requested changes for three concrete findings. Their original
mechanisms and initial source line numbers are preserved below. Initial hashes
and observations are in `independent_review_red.json`; the same probes after
correction, including final source hashes, are in `independent_review_green.json`.

Reviewed production files:

- `infrastructure/scheduling/manager_announcement_supervisor.py`
- `ops/render_manager_announcement_binding.py`
- `v4/manager_research/plan_owner_dispatch.py`
- `apps/api/v35_api/manager_research_router.py`
- `v4/manager_research/workspace.py`
- `v4/manager_research/workspace_plan_autorun.py`
- `ops/run_manager_announcement_cycle.py`

Reviewed adjacent contracts include daily channel assessment, same-run owner
attempt readback, US daily mapping consumption, original API service injection,
and the three R3 test files. This is a targeted review; the supplied source
closure is not the complete application runtime.

## Findings

### R3-REV-1 — P1: input-not-ready is cached as a successful terminal dispatch

**Locations:** `ops/run_manager_announcement_cycle.py:464` and
`v4/manager_research/plan_owner_dispatch.py:720-723` in the initial candidate.

The new admission result correctly avoids writing a plan and returns
`CANNOT_CONFIRM / WORKSPACE_PLAN_INPUTS_NOT_READY`. The cycle adapter labels
that result `PARTIAL`. The existing dispatch cache treats every completed
`PARTIAL` as terminal and immediately returns its prior response. Consequently
the new input diagnostic becomes permanently cached for that trigger identity.

For a PREOPEN trigger, a first call at 09:27 with missing inputs followed by
another call at 09:28 with valid inputs still returns the old diagnostic. The
owner was called once, the two dispatch receipt references were equal, and the
second result had no run ID. PREOPEN and EVENING_NEXT_SESSION identities do not
include a changing minute, so this prevents input readiness from recovering
through the original retries during the same window. This is distinct from
retaining an actual verified `PARTIAL` research product.

**Initial reproducible observation:**

```json
{"first_status":"PARTIAL","first_outcome":"INPUT_NOT_READY","second_status":"PARTIAL","second_outcome":"INPUT_NOT_READY","owner_calls":1,"same_receipt":true,"second_run_id":null}
```

**Required correction:** keep verified owner products idempotent, but allow
input admission failures to use the original bounded retries and backoff.
Do not increase the existing retry budget or create a new producer.

### R3-REV-2 — P2: the response wrapper rewrites other outcomes as OWNER_FAILED

**Locations:** `v4/manager_research/plan_owner_dispatch.py:389-405`, with the
pre-owner expiry branch at `484-487`, in the initial candidate.

`_cycle_result` preserves only explicit `GATE_REJECTED` and `NOT_TRIGGERED`
outcomes. Any remaining failed envelope is reclassified as `OWNER_FAILED`,
even when no owner ran or the subordinate adapter already reported unconfirmed
readback. Two independent compositions reproduce the problem:

1. Admission and serialization checks occur at 09:29:59, then the final check
   immediately before execution occurs at 09:30:00. The owner call count is
   zero; the result has `EXPIRED_NO_BACKFILL` and
   `PLAN_OWNER_WINDOW_EXPIRED_BEFORE_EXECUTION`, but is labeled `OWNER_FAILED`.
2. An owner wrapper returns an apparent `MATERIALIZED` result without the
   required product identity. `run_scheduled_plan_target` correctly marks it
   `FAILED / READBACK_UNCONFIRMED` with
   `PLAN_OWNER_PRODUCT_READBACK_INVALID`; `_cycle_result` changes the outcome
   to `OWNER_FAILED` despite retaining `owner_readback_status=UNVERIFIED`.

**Initial reproducible observations:**

```json
{"case":"window_expired_before_owner","status":"FAILED","outcome":"OWNER_FAILED","owner_calls":0,"reason":["PLAN_OWNER_WINDOW_EXPIRED_BEFORE_EXECUTION"],"plan_status":"EXPIRED_NO_BACKFILL"}
{"case":"explicit_unconfirmed_is_overwritten","branch_status":"FAILED","branch_outcome":"READBACK_UNCONFIRMED","dispatch_outcome":"OWNER_FAILED","reason":["PLAN_OWNER_PRODUCT_READBACK_INVALID"],"owner_readback":"UNVERIFIED"}
```

**Required correction:** retain the established six distinct outcome meanings,
and give a pre-owner window rejection a gate/not-triggered classification.
An unconfirmed readback must not claim that the original owner failed.

### R3-REV-3 — P2: the new historical canary cannot use its required dynamic GET

**Location:** `infrastructure/scheduling/manager_announcement_supervisor.py:347-368`
in the initial candidate, combined with the new explicit owner-identity canary.

The canary reader accepts only the exact URL `/workspace?date=YYYYMMDD` for GET
evidence. The R3 date contract correctly preserves historical `auto` eligibility:
a retrospective 20261008 manual run is read by explicit `view=dynamic`, while
ordinary `auto` does not consume that retrospective run. A new dual-root
historical canary containing the correct `&view=dynamic` readback is therefore
rejected with `PLAN_REFRESH_CANARY_HTTP_EVIDENCE_INVALID` after all receipt
hashes are recomputed correctly.

The fixed legacy URL rule predates R3. The integration incompatibility matters
in this change because a new explicit owner identity requires a fresh canary
bound to the API closure; its retrospective evidence must be producible by the
current API's documented read contract. The baseline migration gate must stay
intact.

**Initial reproducible observation:**

```json
{"scope":"HISTORICAL_MANUAL_REFRESH_WITH_HTTP_READBACK","get_url":"http://127.0.0.1:8873/api/v4/manager/research/workspace?date=20261008&view=dynamic","outcome":"PLAN_REFRESH_CANARY_HTTP_EVIDENCE_INVALID"}
```

**Required correction:** validate the explicit historical dynamic GET for the
new owner-identity contract, including exact target-date and unambiguous query
parameters; retain the legacy canary and source-migration rules.

## Reproduction

Use the native Python 3.14 environment and run from the candidate source root:

```bash
cd /workspace/scratch/6168fe203da9/r3-work/candidate
PYTHONPATH=.:tests /workspace/scratch/6168fe203da9/r3-venv314/bin/python ../evidence/independent_review_probes.py
```

`independent_review_probes.py` reports observations rather than asserting that
the initial bugs remain present, so the identical command can verify corrected
behavior. It does not open any HTTP connection. Its input sources, binding
receipts, canaries, state roots and owner responses are synthetic. Native source
files are only read for hashing and imports.

Observed environment: CPython 3.14.8, Linux x86_64/glibc 2.39; pytest 9.1.1,
FastAPI 0.143.0, Starlette 1.7.0, httpx 0.28.1, Pydantic 2.14.0. This is the
provided relevant test closure, not a replica of the complete Mac runtime.

The three protected Issue32 files were independently rehashed against both
baseline and candidate; all are unchanged and match the fixed task package:

| File | SHA-256 |
| --- | --- |
| `apps/api/v35_api/app.py` | `5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5` |
| `apps/api/v35_api/preselection_router.py` | `718d54a6c6aa8cde2871ce4dc41cbc1d825f199a57b605e4f5ec70d8c4fe19ae` |
| `apps/api/v35_api/preselection_service.py` | `cbed3aa4797889051eb7bebe4b8e3240b568d72b4dfb5c20f65e914d39e48044` |

## Independently confirmed inherited failure

The following unchanged neighboring test was independently executed in both
`baseline` and `candidate` using separate Python processes:

```bash
/workspace/scratch/6168fe203da9/r3-venv314/bin/python -m pytest tests/test_manager_announcement_parity_20261008.py::test_missing_original_archive_is_not_empty_connect_selection -q
```

Both returned exit code 1 and failed at the same test line 381:
`assert value['selection_diagnostics']['status'] == 'READY'`, with actual
`PARTIAL`. Independent runtimes were 0.30 seconds for baseline and 0.26 seconds
for candidate. The parent also retained raw logs in
`r3_existing_archive_baseline_py314.log` and
`r3_existing_archive_candidate_py314.log`. This failure is present in the R1/R2
input base and is not a newly introduced R3 regression. The test was not changed
or suppressed by this reviewer.

## Boundaries

This review does not establish real 20261008 or 20261009 plan materialization,
actual Mac integration, deployed API/UI correctness, or natural execution.
The existing shared-owner policy's blocked paths remain blocked. No policy,
LaunchAgent, automation, production configuration, live source, or live business
state was modified, and no live owner POST or trade was sent.

Final status must continue to distinguish IMPLEMENTED / TESTED from unexecuted
INTEGRATED / DEPLOYED / API / UI / NATURAL acceptance.

## Final independent verification and finding closure

The identical four-probe command above completed with exit code 0 against the
corrected source. The result was saved as `independent_review_green.json`.
Only `manager_announcement_supervisor.py` and `plan_owner_dispatch.py` changed
between the initial and final probe snapshots; all seven reviewed production
files still matched the final verified hashes when checked after the tests.

| Finding / probe | Initial result | Final result | Disposition |
| --- | --- | --- | --- |
| R3-REV-1, input becomes ready on second trigger | Owner called once; old `INPUT_NOT_READY` receipt cached | Owner called twice; second result `OWNER_RESULT` with the original owner run ID and a different dispatch receipt | CLOSED |
| R3-REV-2, expiry immediately before owner | `OWNER_FAILED`, despite zero owner calls | `NOT_TRIGGERED`, zero owner calls, original expiry reason retained | CLOSED |
| R3-REV-2, explicit unconfirmed readback | Rewritten to `OWNER_FAILED` | `READBACK_UNCONFIRMED` retained, owner readback remains `UNVERIFIED` | CLOSED |
| R3-REV-3, new historical dynamic canary | `PLAN_REFRESH_CANARY_HTTP_EVIDENCE_INVALID` | `ACCEPTED` | CLOSED |

The final retry implementation was read independently:
`plan_owner_dispatch.py:410-417` validates the original owner result before
caching it, and `732-753` keeps other completed results within the existing
three-attempt budget and original 60-second / configured evening backoff.
The final outcome mapping is at `389-407`, with explicit pre-owner expiry at
`495-499`. The new historical URL predicate is at
`manager_announcement_supervisor.py:239-253`; its selection at `383-390` is
limited to an explicit owner identity plus HISTORICAL scope, leaving the legacy
URL and migration branches intact.

The full three-file R3 regression set was then run independently in a fresh
Python process:

```bash
cd /workspace/scratch/6168fe203da9/r3-work/candidate
PYTHONPATH=.:tests /workspace/scratch/6168fe203da9/r3-venv314/bin/python -m pytest -q tests/test_manager_r3_binding_identity.py tests/test_manager_r3_dates_inputs.py tests/test_manager_r3_cycle_outcomes.py
```

**Actual result: 120 passed, 1 warning in 6.49 seconds; exit code 0.** The warning
is Starlette's existing httpx TestClient deprecation notice. Raw output and the
command are in `independent_review_final_tests_py314.log`. The set comprises
91 binding/dispatch/canary cases, 15 date/input cases and 14 cycle-adapter cases.

The final tests and code inspection establish these bounded contracts:

- A single raw binding SHA identifies closed worker and API owner inventories,
  and the API's expected root remains independently derived. SHA, enabled,
  root, source drift, overlap, missing files, symlinks and canary mismatches
  reject before an owner call or dispatch-store write.
- A new explicit owner canary requires the canonical JSON owner-identity
  digest. The worker and API may contain different valid source bytes; this
  does not remove the legacy source-migration comparison.
- Verified owner products retain exact run/product/input/attempt readback and
  repeated-trigger idempotency. Input diagnostics can recover after the original
  backoff, share the original bounded failure budget and do not create a
  workspace plan or owner attempt. A valid independent channel can still be
  saved when another channel is unavailable.
- The six dispatch outcomes remain distinct in the tested gate, not-triggered,
  missing-input, owner-failure, verified-owner-result and unconfirmed-readback
  cases. HTTP 200 alone cannot validate the owner result.
- Retrospective 20261008 plans use explicit dynamic readback; normal auto keeps
  its original historical eligibility and can retain a different qualified
  historical run. A saved 20261009 plan is read by normal auto using the same
  date, run, product SHA and input identity without a new write.
- The US capture-only case uses the actual source store/reader and remains
  `daily_run=NOT_RUN`; it cannot authorize a plan. A real synthetic daily owner
  `VALID_EMPTY` artifact consumed before cutoff can authorize a traceable empty
  plan without assigning zero counts to the unavailable independent channels.
- Safety remains `RESEARCH_ONLY=true`, `production_allowed=false`,
  `buy_gate_updated=false`, `orders_sent=false`, and natural verification is
  never inferred from a synthetic or manual run.

## Delivery helper read-only review

At the parent's request, `r3-work/tools/verify_delivery.py` (142 lines) and
`r3-work/tools/assemble_test_fixture.py` (92 lines) were also read in full.
No severe issue was found that would write outside the explicitly selected
output tree, impersonate a release owner, or turn verification into deployment.

The verifier reads the selected bundle/source paths, rejects noncanonical
relative paths and symlinks, verifies bounded regular-file bytes and a closed
inventory, and recomputes forward/reverse patches. Its result explicitly says
runtime identity is not verified and ownership is not granted. The assembler
first verifies the bundle and every selected source SHA/blob, accepts only a
fixed 40-character commit for local `git show`, performs no fetch, and requires
the specified output root to be absent. All output paths are checked before
creation; `sys.dont_write_bytecode=True` is set before importing the sibling
verifier, so that import does not mutate the closed delivery bundle. Its receipt
states `ASSEMBLED_TEST_FIXTURE_ONLY`, `full_runtime_image=false`, and unexecuted
integration/deployment.

This helper conclusion is from code inspection; the parent's separate actual
116-file assembly run is not presented as independently executed here.
