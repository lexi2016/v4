# PDF batch continuation handoff

## Scope and state

This change adds an optional `--continuation-plan` seam to the existing PDF batch runner. The default runner still pins model settings to the original SHA `7a98bb5d2b6687b808d72b8c7bb385a23c714e9753a067fab81407c4e9245b99`. Continuation plans accept only that hash or the separately known `.9375` hash `0da2c9d1044a1d86ac0037f06859248568ba82a03f1a26a17699c64b12e9c7c7`, with runtime SHA `e05af04aa712ee134354a8c0fa97812761cee7d1304b3914c87b6a8636b22a99`. A plan pins one of those known bindings; it cannot accept an arbitrary observed hash.

Plan-only validation reads the frozen manifest, the exact prior R3 progress snapshot, and the prior queue state. It does not inspect current settings, call model identity or inference, create a queue, or write the continuation state directory. Execution saves the exact plan bytes immutably under a separate state directory beneath the existing batch parent. New run-progress rows, document receipts, and queue inputs carry continuation ID, plan SHA, settings SHA, manifest SHA, selected prior status, and a recovery reference when applicable.

The recovery branch accepts at most one `FAILED_NO_RETRY` request, and only under the original settings hash. It binds the exact prior document receipt, queue identity, source SHA, input payload SHA, raw artifact SHA, and parsed `error.code == "prefill_memory_exceeded"`. The new request appends `:recovery:1` to the old article ID in the separate queue. The prior R3 queue and raw artifact are read-only; the new queue keeps `max_attempts=1`. A deterministic recovery state-root name and immutable copied plan prevent a second plan from creating another generation for the same failed identity. Source-repair failures, isolated documents, completed reports, and reused reports are ineligible.

## Frozen pilot reference and sanitized plan template

The frozen R3 snapshot is bound to manifest SHA `e739287d70abaafe428dabe08fb1025308d195dd717053f8189fe5f84ace25c9` and progress SHA `67a658ecc731cd01413523bb9a8cff3393a21e317f4cdfb00f011e055b4fdb84`; the prior progress status is `STOPPED_GRACEFULLY`.

The actual pilot selection remains local at `R/continuation/pilot-selection.json`. Its whole-file SHA is `f94b71c4dd8a204b81492bce9a5e307a7a2cadc5b35056623ed6171e3d76e0f5`, nested `selection.selection_sha256` is `e59ff0eebfbd5bd2a7b16579ca206864064319c34ef758f72c04b25b5d6fd199`, and its state is `PREPARED_NOT_RUN` / `NOT_RUN`. It selects manifest positions 143, 155, 168, 171, 176, 177, 188, 193, 199, and 208; each PDF is at most five pages. The selected document IDs, source hashes, cached-input paths, and full inputs stay in that local artifact and are omitted here. This selection replaces the earlier illustrative first-ten-unprocessed example.

The following JSON is a schema/template only. Placeholder values must be replaced from the frozen local inputs and selection before a plan can be created; this example is not executable and no continuation plan has been created. The `0da2c9d1044a1d86ac0037f06859248568ba82a03f1a26a17699c64b12e9c7c7` value is the known `.9375` candidate binding, not a current live settings read; candidate adoption remains pending.

```json
{
  "schema": "v4.pdf_research_simple_batch.continuation_plan.v1",
  "continuation_id": "<LOCAL_CONTINUATION_ID>",
  "source_run_id": "<FROZEN_SOURCE_RUN_ID>",
  "manifest_sha256": "e739287d70abaafe428dabe08fb1025308d195dd717053f8189fe5f84ace25c9",
  "prior_progress_path": "<LOCAL_PRIOR_PROGRESS_PATH>",
  "prior_progress_sha256": "67a658ecc731cd01413523bb9a8cff3393a21e317f4cdfb00f011e055b4fdb84",
  "prior_progress_status": "STOPPED_GRACEFULLY",
  "runtime_settings_sha256": "e05af04aa712ee134354a8c0fa97812761cee7d1304b3914c87b6a8636b22a99",
  "expected_model_settings_sha256": "0da2c9d1044a1d86ac0037f06859248568ba82a03f1a26a17699c64b12e9c7c7",
  "observed_model_settings_sha256": "0da2c9d1044a1d86ac0037f06859248568ba82a03f1a26a17699c64b12e9c7c7",
  "state_root": "<LOCAL_CONTINUATION_STATE_ROOT>",
  "selected_documents": [
    {
      "document_id": "<LOCAL_MANIFEST_DOCUMENT_ID>",
      "prior_status": "<ELIGIBLE_PRIOR_STATUS>",
      "source_sha256": "<MATCHING_MANIFEST_PDF_SHA256>"
    }
  ],
  "one_time_recovery_limit": 1,
  "excluded_prior_statuses": [
    "FAILED_DOCUMENT_ISOLATED",
    "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING",
    "MODEL_GENERATED_TEXT_PARTIAL_SOURCE_REVIEW_PENDING",
    "SOURCE_REPAIR_FAILED_NO_MODEL",
    "USER_ACCEPTED_REUSED_REPORT"
  ],
  "research_only": {
    "research_only": true,
    "production_allowed": false,
    "buy_gate_updated": false,
    "orders_sent": false
  }
}
```

Repeat the selected-document object in the frozen local plan for each selected row. The validator requires every ID to belong to the frozen manifest and binds each source SHA to that manifest.


All plan files must be SHA-pinned and plan-only validated after creation. The plan validator rejects a document ID that is outside the frozen manifest.

## Commands and state

Before use, bind `PDF_PYTHON` to the configured native/local-model runtime Python executable, and bind `V4_ROOT`, `MANIFEST`, and `PLAN` to the canonical application root and frozen input files. Keep the executable path local; this README uses placeholders. The currently observed native runtime reports Python 3.12.13. The Python 3.14 `uv` environment below is for writer-phase tests only and must not be used as the execution-client interpreter.

Plan-only preflight after a local immutable plan is frozen. Run it from the canonical V4 root so imports resolve from that checkout:

```sh
cd "$V4_ROOT"
"$PDF_PYTHON" -m ops.run_pdf_research_batch --manifest "$MANIFEST" --continuation-plan "$PLAN"
```

Execution pattern for a later controller-authorized run, after independent Reviewer PASS and canonical integration. Run it from the canonical V4 root as well:

```sh
cd "$V4_ROOT"
"$PDF_PYTHON" -m ops.run_pdf_research_batch --manifest "$MANIFEST" --continuation-plan "$PLAN" --execute
```

The execution client must use the configured native/local-model runtime interpreter. Verify the selected local executable with `"$PDF_PYTHON" --version`; do not substitute the temporary Python 3.14 test interpreter.

The writer-phase tests ran under Python 3.14.6 via `uv`.

Writer-phase final verification was `49 passed, 1 deselected`; the focused continuation and affected default-path regressions passed `12/12`. The deselected `test_long_render_uses_existing_two_slice_geometry_and_vision` requires the missing `infrastructure/zsxq_pdf_ingestion.py`. The test wrapper used `uv run --python python3.14 --no-project --with pytest --with starlette python -`, compiled the runner and test source, imported the canonical `infrastructure` package before the edited worktree runner, asserted the runner came from the worktree, then invoked pytest on `tests/test_pdf_research_batch.py -q --tb=short --basetemp=/tmp/pdf-batch-continuation-pytest -k 'not test_long_render_uses_existing_two_slice_geometry_and_vision'`.

This worktree omits `infrastructure/local_document_model.py`, `infrastructure/pdf_research.py`, and `infrastructure/zsxq_pdf_ingestion.py`; no helper was copied. Their canonical source SHAs are `9cf40be4310fed978c74058619b982207efcf82b8d4b891405fd3e27a9a1f930`, `8cac9065f8c3e2661fe8eb03b78a49f3ec4da9786a728b4f9c560088a19a3d88`, and `8a16a457edbd6a7a95c3b3c7af5335d8243946b0e5f2b2f2eb48f5fc3e7c9f9b`, respectively.

Neither CLI pattern was run against a live R3 plan. This docs-only packaging delta did not rerun tests or change source, tests, plans, settings, queues, services, model state, or Git state. No model calls, queue mutations, report writes, or deployments occurred in the writer phase. Current live settings SHA, candidate adoption, independent Reviewer PASS, pilot execution, generated reports, and natural outcomes remain `CANNOT_CONFIRM`; writer status remains `READY_FOR_INDEPENDENT_REVIEW`.
