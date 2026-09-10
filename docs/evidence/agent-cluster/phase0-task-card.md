# Phase 0 Agent Cluster Task Card

## Goal

Independently verify that the V3.5 graph baseline is anchored to the legacy V3 evidence and does not invent business behavior.

## Final Deliverable

A read-only worker handoff covering checked paths, findings, conflicts, confidence, and `CANNOT_CONFIRM` items. The Controller remains the sole writer and final judge.

## Inputs

- `C:/Users/huang/Desktop/学习/v3_system/90_ops/status/v3_full_program_atlas_012`
- `C:/Users/huang/Desktop/学习/v3.5/.runtime/evidence/phase0/v3_current_script_task_graph_20260801`
- `contracts/migration/v35_replacement_inventory.json`
- `ops/migration/graph_baseline.py`
- `tests/test_graph_baseline_v2.py`

## In Scope

- Static Atlas, current task graph, inventory identity, SHA, and reconciliation logic.
- Evidence gaps caused by the missing Atlas 038 directory.

## Out Of Scope

- Editing any file.
- Recommending new models, business rules, data-source priority, or deployment actions.

## Risk Boundaries

- Legacy V3 is read-only.
- `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.
- Worker `READY` is not Gate 0 acceptance.

## Agent Cluster Decision

- Use cluster: yes, at the user's request for model capability separation.
- Controller/writer: Codex/Sol.
- Read-only graph investigator: Luna/Explorer.
- Gate reviewer: Reviewer.
- Numerical judge: deterministic Python.

## Acceptance Criteria

- Every material claim cites a path, field, or deterministic command.
- Unresolved graph identities remain `CANNOT_CONFIRM`.
- Controller independently reruns tests and validates generated contracts.

## Stop Rules

- Stop and report if a finding would require changing legacy V3 or business semantics.
- Mark `CANNOT_CONFIRM` when the missing Atlas 038 source cannot be reconstructed from current evidence.
