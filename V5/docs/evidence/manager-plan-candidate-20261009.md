# Manager original-owner wiring candidate

Parent: `4a6e582eb6a7ff73e1de999cbe5be0b982e4c889`.

Actual Mac RED on the parent: 7 tests, 1 PASS / 2 FAIL / 4 ERROR. The two
failures establish incorrect consumption of US07 at a US08 cutoff. The four
`vibe_binding_preflight` import errors are not behavioral RED. This candidate
adds that exact original dependency, SHA
`b5b108f8e327b67ef43fd91ce33da936b2cfc7a67dae3b0f129071dff8c6554d`.

## Changes

- The immutable original fixture remains a contrast, with its regression run
  isolated in a subprocess. Its expected five behavioral failures are checked
  explicitly; any import error fails the wrapper. No `v4` namespace leaks into
  the full suite.
- A separate production capsule modifies only the admission call in original
  workspace.py and adds the session/source validator. All origins and changes
  are recorded in `contracts/manager_plan_source_manifest.json`.
- `manager_plan.run_manager_plan` binds SHA-verified private copies of saved
  announcement/body/analysis records, saved US daily output and exact US source
  files. It calls original get_workspace or refresh_workspace_plan; it never
  imports service.py or runs a collector. Missing lanes retain original gaps.
- Plan writes use original workspace_plans/workspace_plan_runs, followed by
  independently instantiated original `_read_plan` and `verified_plan_attempt`.
  Run ID, input identity, SHA and terminal attempt are checked.
- Explicit `publish_workspace_read` binds the result to the existing immutable
  module API and ordinary `/api/v4/manager/research/workspace?date=T&view=auto`.
  The serving GET only reads published bytes; it cannot refresh or compute.
  This is code wiring, not a deployed or UI-verified route.

Admission uses G <= Cp, Cd <= Cp, original calendar S(Cd) = S(Cp), target,
current bridge readiness/session and all source identity paths plus payload,
receipt and manifest SHAs. Earlier daily cutoffs and second-truncated generation
remain allowed. No Cd == Cp, daily/workspace identity equality or Cd <= G gate.
The check executes inside the original computation, before saved-context/current
runtime overlays. Rejected daily records remain visible but their SHA does not
enter admitted plan identity. Original after-cutoff rejection is retained.

## Mac verification (existing task only)

```sh
PYTHONDONTWRITEBYTECODE=1 python3 V5/tests/fixtures/manager_owner/check_original.py -v
PYTHONPATH=V5/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s V5/tests -p 'test_manager_plan*.py' -v
```

First command intentionally remains RED (expected five failures, zero errors).
Second command tests subprocess isolation, admission positive/negative cases,
actual production adapter, independent original persistence/readback, rejected
SHA exclusion and an actual loopback ordinary module API GET. The baseline
control is included in discovery; it is not excluded from the full suite.

Cloud validation is only AST, source SHA, diff and source review. All tests of
this new candidate are NOT_RUN until the existing Mac task reports.

## Explicit real-input request

`run_manager_plan` takes a JSON object with these exact keys:

```json
{
  "target_date": "20261009",
  "now": "<aware actual composition cutoff, after the saved daily generation>",
  "action": "refresh",
  "view": "auto",
  "selection_date": null,
  "announcement_date": null,
  "inputs": {
    "manager": {"root": "<private V5 owner input root>", "files": {"<saved daily pointer and run paths; announcement paths if available>": "<raw file SHA256>"}},
    "materials": {"root": "<private material root>", "files": {}},
    "us": {"root": "<US08 exact source root>", "files": {"<three exact paths>": "<raw file SHA256>"}}
  },
  "rebound": null,
  "manager_output_root": "<separate existing V5 plan output root>"
}
```

Output root requires `.v5-manager-plan-root` containing exactly
`v5.manager-plan-root.v1\n`. Inputs may be read from existing roots, but all
original-reader operations including US lock creation use temporary private
copies. Output must not overlap an input root. Empty files maps mean unbound
owners; they do not mean verified empty results. This request format does not
inherit ambient V4 environment bindings.

The confirmed US09 daily run is `f21f72f3e0dc44bf9f98d4436e7dbe9d`, artifact
SHA `8dbcd6dfd52d3e8369c9f3fdb48ac591599a3901f6b854de21c901004da3db05`.
Bind its actual saved latest pointer and runs/<run_id>.json, plus US08 payload,
receipt and manifest. VALID_EMPTY/0 matches, MANUAL_RECOVERY and CANNOT_CONFIRM
eligibility must remain unchanged. Never insert the prior day's two matches.

With a prepared request, the independent Mac task can explicitly run:

```sh
python3 V5/tools/check_manager_plan_request.py /absolute/path/manager-request.json
```

This saves a manual plan, invokes a second production adapter read and requires
same plan run plus current US daily consumption. It is not invoked automatically
and has not been run in the cloud.

## Remaining limits

- No deployment, preview switch, production process, natural execution or trade.
- No current real announcement/body inputs have yet been supplied to this
  adapter; original readers are bound but real consumption remains unverified.
- Rebound committed references are read through existing `read_shadow`; current
  `parse_result` explicitly rejects successful OWNER_VERIFIED results. The
  adapter therefore cannot upgrade existing unadmitted/synthetic rebound output;
  it reports `V5_REBOUND_OWNER_ADMISSION_UNVERIFIED` with original unknown screen.
  Full real oversold owner admission remains required before the three-lane
  milestone can be claimed complete.
- Original prior continuity dependencies (manager_condition_evidence and related
  attestation) and stage scheduler dependencies remain absent and are caught as
  original gaps. No stage/continuity verification is claimed.
- Python I/O guards constrain pinned owner writes, not an OS sandbox. UI GET is
  immutable record serving; publication and refresh are explicit operations.

## Mac result and OverlayIO correction

Mac tested fixed `7cec9de2ddd40c1572409b8bd3f07b3f01cd90e1`:
original control 2 PASS / 5 FAIL / 0 ERROR (exit 1, 0.200s); candidate suite
2 PASS / 6 ERROR (exit 1, 1.899s). All six errors were
`AttributeError: 'OverlayIO' object has no attribute 'files'`. Real US09 manager
request execution was not reached; its existing owner artifacts were preserved.

The correction delegates `files(relative=None, *, suffix='.json')` to the
original SafeRoot selected by the same prefix routing as `read_bytes` and
`directory`: durable plan directories versus private original-owner inputs.
It preserves original suffix filtering, sorted regular-file validation and
missing-directory behavior. No mock, empty-list substitute or assertion change.

Static audit of the frozen manager owner found three overlay read interfaces:
`read_bytes`, `directory`, `files`. Constructor `ensure_directory` executes before
the overlay is installed; `_transaction` and `_write_atomic` explicitly delegate
to the durable original store's own SafeRoot (`kernel_lock` / `write_bytes`).
MaterialStore and US reader own separate SafeRoot instances. They do not use
this overlay. The six existing adapter tests remain the regression coverage.
Cloud validation for the correction: AST parse and git diff check only;
Mac rerun and real US09 manager request remain NOT_RUN on this correction.

Added an original-SafeRoot regression for the production OverlayIO class using
real populated private and durable directories, conflicting owner entries,
`.json`/`.txt` suffix filtering, exact first-component routing, no-argument and
missing-directory reads, read_bytes/directory delegation and unchanged bytes.
The class was lifted out of `_assemble` solely to exercise that same production
protocol directly; `_assemble` instantiates it with its original durable/private
SafeRoots. The existing eight outer tests remain; the candidate subprocess now
contains six tests rather than five. No mocks or original assertions were removed.
