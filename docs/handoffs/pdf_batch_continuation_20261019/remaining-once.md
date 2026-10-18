# Finite PDF continuation dispatcher

Status: **PREPARED_NOT_AUTHORIZED**. This handoff describes the prepared dispatcher only. It does not authorize a pilot, model call, queue operation, or state write. The dispatcher refuses `--execute` unless the separate root authorization file exists and all bound evidence validates.

The runner is the integrated `ops.run_pdf_research_batch` module. The dispatcher plans one document, asks that runner to validate the immutable singleton plan, records `dispatch_intent`, executes the runner, and reconciles the per-document receipt and progress row before it can select another document. It never creates future plans in advance. Each new document receives its own `continuation-<id>` state root. A deferred document can resume only from its saved bytes and the same state root.

The eligible set is derived from the frozen 2,209-row manifest and original R3 progress file. It excludes all 142 original progress rows, the ten documents in the completed R2 pilot, the quarantined manifest row 143, and every document already recorded in the dispatcher ledger. With ten successful pilot receipts and no prior continuation attempts, the expected starting count is 2,056. The dispatcher checks this count before its first plan.

## Execution gate

The configured runtime is Python **3.12.13** at `/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python`. The earlier draft’s Python 3.14.6 command is stale and must not be used for execution. The runner remains bound to SHA-256 `53b94d869d380ac33d2f5a51ab278aa502c2be610b40241e09503c45b5f29007`.

Root may create `continuation/ROOT_REMAINING_EXECUTION_AUTHORIZATION.json` only after the actual ten-document pilot has ten reconciled successful receipts, the resource gate and both content sentinels pass, an independent Reviewer passes this dispatcher, and root adoption is recorded. The authorization file must use schema `v4.pdf_remaining_once.execution_authorization.v1` and bind these fields:

```json
{
  "schema": "v4.pdf_remaining_once.execution_authorization.v1",
  "status": "AUTHORIZED",
  "authorization_id": "lowercase-unique-id",
  "scope_sha256": "<frozen scope SHA-256>",
  "dispatcher_sha256": "<reviewed dispatcher SHA-256>",
  "runner_sha256": "53b94d869d380ac33d2f5a51ab278aa502c2be610b40241e09503c45b5f29007",
  "manifest_sha256": "e739287d70abaafe428dabe08fb1025308d195dd717053f8189fe5f84ace25c9",
  "original_progress_sha256": "67a658ecc731cd01413523bb9a8cff3393a21e317f4cdfb00f011e055b4fdb84",
  "runtime_python": "/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python",
  "runtime_version": "3.12.13",
  "model_settings_sha256": "<adopted pilot settings SHA-256>",
  "max_documents": 2056,
  "pilot": {
    "plan_sha256": "d9c8a6ce47b5e0fd723f40f91b4aa0d11fe8c5f4e9c4195ef0e066b8c0a56c87",
    "selection_file_sha256": "6428b8e14520e70b4cb578b4b9642c38d1a868056ce4229e605d1046b167abac",
    "selection_sha256": "086f60a515eb0ca75294e7734ac14dc3ccfa58add84e3e3a863206748480a4b3",
    "progress": {"path": "<pilot state root>/run-progress.json", "sha256": "<actual progress SHA-256>"},
    "receipts": [
      {"document_id": "<pilot document SHA-256>", "path": "<pilot state root>/documents/<id>/receipt.json", "sha256": "<actual receipt SHA-256>"}
    ]
  },
  "resource_gate": {"path": "<R continuation evidence JSON>", "sha256": "<file SHA-256>"},
  "sentinel_gate": {"path": "<R continuation evidence JSON>", "sha256": "<file SHA-256>"},
  "reviewer_receipt": {"path": "<R continuation Reviewer receipt JSON>", "sha256": "<file SHA-256>"},
  "adoption_receipt": {"path": "<R continuation root adoption JSON>", "sha256": "<file SHA-256>"},
  "research_only": {
    "research_only": true,
    "production_allowed": false,
    "buy_gate_updated": false,
    "orders_sent": false
  }
}
```

All evidence paths must resolve under the R continuation directory. Pilot progress and receipt paths must exactly match the frozen pilot plan’s state root and selected document IDs. Each pilot receipt must be a successful, research-only receipt bound to the R2 pilot plan, manifest, and adopted settings. The four referenced evidence JSON files must carry their expected status (`PASS`, `ADOPTED`, or the documented accepted equivalent) and bind the R2 plan, selection, and actual pilot progress SHA. The resource receipt must report at least 8 GiB minimum available memory, no more than 512 MiB swap-used growth, and ten successful pilot receipts. The sentinel receipt must identify the two frozen sentinel documents and report a pass. The independent review receipt must bind this scope and dispatcher SHA.

## Running after authorization

From the canonical V4 checkout, root can run the preparation-only check without reading pilot receipts or original R3 progress:

```sh
/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python -m ops.run_pdf_research_remaining_once
```

Only after root has created and verified the separate authorization artifact may execution begin:

```sh
/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python -m ops.run_pdf_research_remaining_once --execute --max-documents 2056
```

The authorization’s `max_documents` is the cumulative ceiling across invocations; `--max-documents` is only a smaller per-invocation cap. The journal and resource samples are written under `continuation/resume-writer/`. The journal is append-only and locked. It records plan bytes before plan-only validation and fsyncs `dispatch_intent` before starting an execution child.

The supervisor samples only the existing psutil system-available-memory and swap-used metrics. If a threshold fails or a sample becomes unavailable, it sends at most one cooperative `SIGTERM` to its direct child after checking the child’s process creation time, then waits for the child to finish; it never force-kills. It starts no following plan after a resource stop, `FAILED_NO_RETRY`, an unknown terminal status, an incomplete or mismatched receipt, or an ambiguous dispatch. A source-only status may continue only when its status explicitly indicates zero model work. A deferred outcome is resumed with the same saved plan and state root.

No execution authorization has been created as part of preparation. The ten-document pilot, live settings, queue, state roots, and full-corpus text/cache validity remain outside this preparation receipt and are `CANNOT_CONFIRM` here.
