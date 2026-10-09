# Suggested GitHub/Chat payload

Upload or attach these exact files for the Chat source repair request:

- `FIX_REQUEST.md`
- `REPRODUCE.md`
- `source/managerWorkspace.active-before.ts` (reference only; exact active baseline)
- `source/managerWorkspace.candidate-after.ts` (reference only; faulty frozen candidate)
- `tests/issue8R2.spec.ts`
- `tests/fixtures/issue8R2.fixture.ts`
- `tests/fixtures/issue8R2.ownerObservations.json`
- `tests/managerWorkspace.threeChannel.spec.ts` (preserve new contract)
- `tests/managerWorkspace.dailyAutomation.spec.ts` (adjacent focused regression context)
- `reviewer/final_frontend_deployment_gate_20261009.md`
- `reviewer/legacy-frontend-failure-classification.json`
- `reviewer/logs/rollback_base.log`
- `reviewer/logs/integrated_candidate.log`
- `MANIFEST.json`

These are the exact bounded materials. Do not upload full candidate/rollback trees, runtime state, API responses, caches, `node_modules`, credentials, or production data. The active-before/candidate-after snapshots are diagnostic inputs; the only requested source repair is the single `managerWorkspace.ts` module.
