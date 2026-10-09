# Manager validator restoration implementation plan

> For agentic workers: execute with Superpowers executing-plans; independent review follows the implementation.

**Goal:** Restore the active manager workspace validation contract in the integrated candidate without losing the three-channel contract.

**Architecture:** Change only `apps/web/src/api/managerWorkspace.ts`. Restore the exact active validation functions, required helper, and calls; keep all existing candidate additions byte-for-byte.

**Tech stack:** TypeScript, Vitest 4.1.10, Node 24.19.0; Python-owned synthetic fixtures for adjacent specs.

**Spec:** `input/FIX_REQUEST.md`, frozen repository commit `63e75b7af02866c2d19a484b9561416cb13efd84`.

## Global constraints

- Do not edit unrelated modules, weaken validators, change tests to skip failures, or change trading/BUY behavior.
- Run the identical 76 Issue8 R2 tests against active and candidate sources; then preserve the 25 adjacent three-channel/daily-automation tests.
- Preserve unknown/missing input, source/PIT boundaries, and separate candidate verification from Mac deployment/API/UI/natural-run status.
- Sync necessary code, test evidence and handoff to a new GitHub branch; do not switch services.

## Review focus

- Optional fields absent in historical payloads remain readable; present malformed values are rejected.
- Observation membership identity must agree with source witnesses and target date.
- Observation and evidence clocks retain explicit timezone and PIT order checks.
- Null unknown screen counts and valid zero counts retain distinct acceptance behavior.
- Restored display checks run after nested validation and before successful return.

## Task 1: Restore the validation contract

**Files:** modify the candidate `apps/web/src/api/managerWorkspace.ts`; tests remain byte-identical to `input/tests/`.

- [x] Reproduce 76/76 active and 45-failed/31-passed candidate tests and record failed identities.
- [x] Restore the four active interface declarations, optional properties, `observationTime`, `validateIndependentObservations`, `validateResearchInputDiagnostics`, `validateResearchDisplayConsistency` and their three call sites from the active source.
- [x] Run the unchanged 76 and 25 tests against the repaired candidate; compare the recovered failure IDs with the frozen Mac classification.
- [x] Run changed-source typecheck and inspect the source difference for unintended edits.
- [x] Obtain independent review and preserve its findings with evidence.
- [ ] Build the minimal patch, complete before/after files, SHA manifest, rollback/apply verification, exact logs and Mac instructions; sync and read back GitHub. (Package construction and patch checks complete; remote readback is the final publication step.)
