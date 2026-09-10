# Worker Handoff

> **SUPERSEDED — historical pre-freeze inspection only.** The controller rebuilt the
> contracts from immutable raw-byte inputs after detecting two additional legacy
> source changes. Current authority is baseline semantic hash `8b4b933...`, with
> `316 MATCHES_ATLAS / 20 MODIFIED_SINCE_ATLAS`, status
> `STATIC_RECONCILIATION_PASS_WITH_RUNTIME_GAPS`, and
> `runtime_accepted=false`. The counts and status below are retained only as the
> original read-only Explorer observation and must not be used as the Gate 0 result.

## Instance

- Instance ID: `phase0-graph-lineage-20260801`
- Agent Type: `graph-lineage-auditor` / Luna Explorer
- Assigned scope: Atlas012, refreshed task graph, inventory v1, graph baseline v2
- Status: `SUPERSEDED_HISTORICAL_PARTIAL`

## Result

The composite baseline is reproducible and all Atlas/inventory count differences are explained. It is not runtime acceptance because the refreshed V3 graph still contains four findings and six feature records are not linked to current graph nodes.

## Evidence

| Claim | Evidence | Notes |
| --- | --- | --- |
| Atlas authority is valid | `v3_full_program_atlas_012/validation.json` | PASS, semantic hash `912718...`, 336 files, 90 entrypoints, zero parse gaps |
| Current graph was refreshed | `.runtime/evidence/phase0/v3_current_script_task_graph_20260801/*.json` | 35 task specs, 36 actual tasks, 783 nodes, 1017 edges, four findings |
| Differences are explained | `contracts/migration/v3_graph_baseline_v2.json` | Atlas-only sources 2, v1-only source 1, Atlas-only entrypoint 1, unexplained 0 |
| Current source bytes are frozen | `contracts/migration/v35_replacement_inventory_v2.json` | 318 match Atlas, 18 modified, 0 missing |
| Task identities are linked | inventory v2 `runtime_tasks[*].graph_node_ids` | 69/69 non-empty |
| Feature identities remain partial | inventory v2 `features[*]` | 5/11 linked; 6 explicitly marked `GRAPH_NODE_NOT_RECONCILED` |

## Confidence

- High: counts, SHA, reconciliation, source-state and safety fields.
- Medium: feature lineage inherited from inventory v1.
- Low: reconstruction of the absent Atlas038 source directory.

## Conflicts

| Conflict | Compared against | Impact | Resolution |
| --- | --- | --- | --- |
| inventory v1 hash `4123...` differs from Atlas012 `912718...` | v1 contract vs current static Atlas | v1 cannot be current authority | Retain v1 only as historical reconciliation input |

## CANNOT_CONFIRM

| Item | Reason | Minimum evidence needed |
| --- | --- | --- |
| Original Atlas038 content | Original directory absent | Original immutable Atlas038 artifacts or equivalent signed archive |
| Six feature graph identities | No current node mapping yet | Phase 4 feature-specific graph contracts |
| Runtime health | Four current graph findings | Workload-by-workload fixes and receipts |

## Handoff Notes

The historical `PASS_WITH_EXPLAINED_GAPS` label was replaced by the scoped
`STATIC_RECONCILIATION_PASS_WITH_RUNTIME_GAPS`; neither is deployment or runtime
readiness.
