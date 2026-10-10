# Independent portable handoff review

## Verdict

**APPROVE** the reviewed portable tools and refreshed handoff documentation. The one actionable finding was fixed and concretely verified. No remaining blocking tooling or documentation finding was identified. Application implementation approval belongs to the separate frontend/backend/integration reviews.

Reviewed package: `delivery/V4_MANAGER_LIVE_UI_API_REPAIR_20261010_R1`. Scope: `tools/verify_delivery.py`, `tools/verify_source_gate.py`, `tools/run_offline_tests.py`, `README.md`, `REPAIR_REPORT.md`, `MAC_ACCEPTANCE.md`, and `test_support/README.md`; supporting runners and final portable reports were inspected for consistency. Final assembly may add this review and regenerate the manifest; the observed 126-file manifest is the current reviewed assembly, not an immutable claim about a later ZIP.

## Finding D1 — document application could bypass failed SHA gate — CLOSED

The original application and reverse blocks in `MAC_ACCEPTANCE.md` used independent newline commands. Pasting that block into an ordinary shell allowed later patch commands after a failing source gate. A temporary copy of `test_support/current` plus `before` reproduced the risk: modifying only unchanged `apps/web/src/api/managerWorkspace.ts` made the gate exit 1 / FAIL_CLOSED, but `git apply --check` and `git apply` both exited 0, and the product `workspace.py` changed. Patch-context checks do not verify unchanged prerequisite files.

Root changed each application/rollback sequence to a failure-short-circuiting `&&` chain and also chained the README package verification before offline testing. I executed the actual revised documentation blocks against temporary before/after copies with that same prerequisite drift. Both exited 1 from the source gate, and the product file stayed byte-for-byte unchanged. The finding is resolved. Concrete checks are recorded in `work/reports/delivery_audit/tool_checks.json`.

## Tool findings

### `verify_delivery.py` — PASS

The verifier checks normalized relative manifest paths, rejects duplicates and self-reference, verifies SHA/size, rejects symlinks and unmanifested files, and keeps optional reports outside the package. Temporary mini-fixtures accepted an exact manifest and rejected hash drift, size drift, duplicate paths, parent traversal, and extra files. An output path inside the package was rejected with exit 2 before creating it.

Patch replay assembles only a temporary application tree, calls the same source gate on before/after/reversed trees, checks forward and reverse application, and compares exact whole-tree inventories so extra undeclared patch changes cannot pass. Subprocess errors and timeouts are nonzero. It does not touch a service or application directory supplied by a user.

The actual final assembly verification in `work/reports/delivery.verify.json` reports PASS, 126 checked files, seven runtime files, forward exact / reverse exact, temporary-tree-only, and `LIVE_API_UI_NOT_RUN`. The observed manifest SHA is `2f318867fb0bf0438d4c86f7921ef20d57b487f835efb45626f674e13fbce906`. This is recorded verification evidence, not a claim that this reviewer re-ran application regression suites.

### `verify_source_gate.py` — PASS within its documented trusted-manifest use

The source gate is read-only and compares all seven runtime targets plus nine unchanged prerequisites. It rejects resolved paths outside the selected app root and requires the new module to be absent on the before side. Temporary fixtures confirmed exact before inputs PASS with 16 checks, prerequisite drift FAIL_CLOSED, and a pre-existing new identity module FAIL_CLOSED. The repaired documentation now ensures its nonzero exit actually prevents the following application/rollback action.

The gate is a byte-identity prerequisite check, not full application compatibility proof or manifest authentication. Package verification precedes it in the instructions; the source manifest's parent commit is explicitly a retrieval/handoff anchor rather than the live deployment baseline.

### `run_offline_tests.py` — PASS

The portable wrapper builds temporary before/after snapshots from packaged current support and the chosen source side. It calls delivered runners with explicit source/support/test/report locations, inherits the selected Python interpreter, allows an explicit Node path, suppresses Python bytecode writes, and returns nonzero if any suite fails. Reports remain outside the package; an inside-package report directory was rejected with exit 2 and no directory created.

No fetch/install step, owner execution, live HTTP invocation, service restart, scheduler modification, or deployment is part of this wrapper. Dependency fallback remains limited to the frozen packaged support, with loaded-module identities retained by the runners. Missing runtime executables or unsupported Node features cause failure rather than a successful report. The tools are portable offline test entrypoints, not production installers.

## Documentation findings — PASS

The refreshed README/report state final **35 backend PASS / 22 frontend PASS**, and the delivered portable after reports corroborate those counts. Portable before reports contain **35 backend tests / 17 assertion failures / 0 errors**, plus **1 frontend PASS / 21 FAIL / no setup error**. The original 14-case and intermediate 20-case red evidence is described separately rather than presented as the same final suite. Normal npm testing remains NOT_RUN because the input lacks a complete project; offline Node transforms are not described as type checking or a Vue/Vite build.

The package clearly separates the seven-file product patch from full before/after files, synthetic tests, and frozen support. `test_support/current` is distinguished from `upstream`; the latter's deployed SHA remains unverified. Repository retrieval anchors, exact recovered preimages, original uploaded bytes, support source inventories, and loaded-module hashes are distinguished from evidence of the running app. Current documentation links checked in this scope resolve.

Mac instructions target a newly created complete isolated candidate and require exact source gates around patch application and reversal. They explicitly forbid copying test support into production, overwriting the live app, re-sealing historical plans, and reversing a patch directly against a running directory. Live owner/API/UI work and deployment require separately authorized execution. The matrix preserves the original fail-closed stale behavior, same-run/product/date consistency, scoped US population, raw-row retention, date independence and research-only flags.

Truthful limits are prominent: `PROPOSAL_ONLY / LIVE_API_UI_NOT_RUN`; no Mac service/owner or natural-session acceptance; no real-browser layout/paint/native details click/navigation/bundle identity; module/plan transitions are not complete `_compute_workspace` or HTTP execution. The retained attention benchmark is explicitly attributed to its previous frozen helper SHA, not silently to the final helper, and is not claimed as live latency. Historical unique live changed field and missing owner/data evidence remain `CANNOT_CONFIRM` or NOT_RUN.

The original `frontend.review.md` is now explicitly marked as archival approval of `frontend_01` and its review-time 20-case evidence. The mutable green report was later replaced, and final cap/candidate approval belongs to `integration_03`; the clarification prevents later report lookup from changing the apparent scope of that earlier approval.

## Reviewed identities

| Scoped file | SHA-256 at final review |
| --- | --- |
| `README.md` | `d9f2e36f74a2c2fb5f24bfa40a8266f4062abb33c92eb9a7955a9ef4ab884e67` |
| `REPAIR_REPORT.md` | `e10714e31d035b73b9a4aa6a83a523fc4b3ae1182ce688ea19aa10e50e97518c` |
| `MAC_ACCEPTANCE.md` | `f338cb27946a5ebd9ccca76075a24844e88b67aca1000470d2435c55776c630d` |
| `test_support/README.md` | `e84735a5c2e0d8c39f07dbc8e99866a685c760aec83a15958db346f5a064bd73` |
| `tools/verify_delivery.py` | `576d5716266d859d8c2c10ba4ce92763772a1f22c7a8afb67cf6a552917b0e82` |
| `tools/verify_source_gate.py` | `6493da28cf7cf7fb4dbc5ceb1498f4aca752354058ebd03a1072bbb75dc2966c` |
| `tools/run_offline_tests.py` | `c55adfdaa1adcb4296ac6fe4cb2976cc3434bc4ba0abeb5641615b8b3b5efef7` |

No package application source was edited by this reviewer; checks used temporary fixtures and copies. One import-generated verifier bytecode file was immediately removed to restore the package. No broad application suites, live services, owner operations, or GitHub operations were run during this handoff review.
