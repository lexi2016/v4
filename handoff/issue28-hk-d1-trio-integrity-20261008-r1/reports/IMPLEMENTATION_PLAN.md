# Issue 28 HK Stage candidate plan

Baseline: `30ad7bb633f715f30c4e10eb67e9041de92cf036`, original 52 package members plus the separate Git sync note. All 51 listed SHA256 values, all 53 remote blob SHA and byte sizes verified. Work is isolated; the frozen package and previous deliveries remain unchanged.

## Findings and scope decision

The reported 20261008 / STAGE_0930_0935 input must remain CANNOT_CONFIRM: it lacks split-date provenance and upstream manifest/receipt identities, its 100 reported row signal dates are 20260930 rather than calendar-required 20261007, and no verifiable eligibility run/artifact/capture chain or original upstream price trio is provided. The two independent source layers must not be mixed. Local pool artifact 62d771... and its physical manifest/receipt cannot become the upstream D1 identity whose artifact is ce4e94....

The safe candidate targets a separate, concrete gap in the same integrity contract: the validator verifies the physical trio early but at return checks only the artifact hash and resolver owner. A manifest/receipt change after the early snapshot can escape this final check. Establish RED on both exact source owners before changing implementation, then recheck the full physical trio and the owner/path identity at return. Keep the public validator return contract, upstream provenance comparisons, date/market/Top100 guards, and safety flags unchanged. No new runtime provenance fields or producer are required.

## Execution

1. Assemble two source-pinned test roots using all 13 exact files per owner and separately inventoried historical support; do not represent support provenance as the complete current Mac runtime.
2. Preserve and run the supplied historical test unchanged. Record any baseline fixture/version failures independently of the new regressions.
3. Add synthetic 20261008 regressions for missing provenance, stale row prices after complete provenance, missing upstream hashes despite a valid physical trio, capture dates, valid complete input, and late physical manifest/receipt changes in both primary and secondary paths. Fixtures are not recovered business evidence.
4. After RED, apply the same minimal helper change to canonical and actual Stage candidates. Run focused GREEN and the unchanged baseline suite; compare failures rather than hide them with xfail or skips.
5. Independent reviewer re-runs targeted tests on final byte identities and assesses compatibility, source identity, no-write behavior, and scope.
6. Deliver full before/after file, unified patch, source/support/test manifests, actual commands and raw logs, owner mapping, remaining source requirements, and safe Mac acceptance/rollback instructions. Use the existing AGENTS.md bounded new-branch sync authorization for necessary changed handoff bytes; no merge, services, schedules, business data, or deployment.

## Acceptance limits

The candidate's tests can establish source-level integrity behavior only. No current owner integration, Mac re-execution, API/UI integration, deployment, natural run, missing source reconstruction, or stage recovery is claimed. SETTLED_PARTIAL may prevent automatic rerun even after a separately authorized deployment; API HTTP 200 is readback, not runner execution. Original failure evidence remains authoritative for the current incident.
