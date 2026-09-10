# Phase 0 Cross-Verification

## Result

`PASS_STATIC_RECONCILIATION_ONLY`

This gate establishes a reproducible graph and inventory baseline. It does not
accept V3 runtime health, deployment, BUY-gate changes, or orders.

## Cross-Verification Matrix

| Subject | Explorer observation | Reviewer challenge | Controller resolution | Final state |
| --- | --- | --- | --- | --- |
| Atlas authority | Atlas012 PASS, 336 sources, 90 entrypoints, zero parse gaps | None | Preserved Atlas inputs as raw bytes and bound their SHA | PASS |
| Legacy byte state | Initially observed 318 Atlas matches and 18 modifications | Two legacy files changed after the first build | Superseded the historical handoff; froze the later 316/20 state in a 343-file immutable input snapshot | PASS |
| Inventory lineage | 69/69 runtime records linked; 5/11 features linked | Fabricated graph IDs and evidence-free COMPLETE were initially accepted | Added a 1,209-ID registry, membership validation, inventory semantic hash, and structured replacement evidence | PASS |
| Acceptance label | Historical label could be read as a broad PASS | Runtime graph still has four findings | Replaced it with `STATIC_RECONCILIATION_PASS_WITH_RUNTIME_GAPS`; set runtime/deployment acceptance false | PASS |
| Fail-closed structure | Initial focused tests passed | Missing/null sections and inconsistent counts could be rehashed | Added strict section shapes and static/runtime/registry cross-count validation with negative tests | PASS |
| Entrypoint identity | Atlas Windows Task fallback was required | Common identity path changes were not compared | Added Atlas-versus-v1 path mismatch rejection | PASS |
| Model routing | Explorer performed lineage work only | Reviewer required an explicit acceptance gate | Codex/Sol remained sole writer; Explorer and Reviewer remained read-only; deterministic Python owns counts and hashes | PASS |

## Independent Review History

- Round 1: `REQUEST_CHANGES` for invented lineage, non-reproducible live bytes,
  ambiguous PASS scope, and missing fail-closed checks.
- Round 2: `REQUEST_CHANGES` for null required sections, invalid COMPLETE
  evidence, and a stale Explorer handoff.
- Round 3: `REQUEST_CHANGES` for runtime/registry count linkage.
- Final round: `PASS`; no remaining P1 or P2.

## Accepted Gaps

- Original Atlas038 contents: `CANNOT_CONFIRM`.
- Six feature identities: `GRAPH_NODE_NOT_RECONCILED` and not eligible for
  migration until Phase 4 supplies graph evidence.
- Four refreshed runtime-graph findings: carried forward; runtime acceptance is
  false.
