# V3 PDF research sample handoff

This handoff covers only the frozen V3 PDF research canary path. The implementation is isolated under `infrastructure/local_document_model.py`, `infrastructure/pdf_research.py`, and `ops/run_pdf_research_sample.py`. Its queue, result, receipt, and source-manifest writes are confined to the existing `external_sources/zsxq_hourly/pdf_local/research/` prefix. The PDF queue shares the pinned announcement model lock, while keeping its queue state separate from announcement state.

## Current phase

`C1_SEMANTIC_REPAIR_CANDIDATE`: the first S01 real canary remains `FAILED` under its original response contract, and its raw response is not reusable as accepted analysis. This repair is offline only. No new model completion, API GET, OCR, download, input PDF mutation, page-cache mutation, announcement-state write, or business-data write has been performed during this semantic repair. Accepted runtime binding evidence is immutable; server launch identity and active in-memory memory settings remain `CANNOT_CONFIRM` unless that evidence says otherwise.

The first canary is S01 from the frozen 20-document manifest. Plan-only selection is pinned to that one document and has no inventory fallthrough. `--execute` remains blocked in the offline phase until an independent source-review PASS and a separate parent-frozen `execution-scope-receipt.json` exist. This repair accepts only `CANARY` execution for S01; `SAMPLE` execution is unsupported. The accepted `runtime-binding-evidence.json` remains immutable. The CLI no longer captures or replaces it; runtime, model, or helper drift fails closed.

Supported invocation is module form using the approved runtime:

```sh
PYTHONDONTWRITEBYTECODE=1 /Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python -m ops.run_pdf_research_sample --phase CANARY
```

Adding `--execute` does not bypass any execution gate.

## Execution-scope receipt contract

The parent-issued receipt path is `/Users/lexi/Desktop/学习/agents调试/V4_PDF_RESEARCH_V3_SAMPLE_20261018_R1/execution-scope-receipt.json`. It must be a regular non-symlink JSON file with schema `v4.pdf_research_v3.execution_scope.v2`, status `FROZEN`, and `authorized_by` `/root`. The CLI checks all of these bindings against current frozen inputs and source review before any research-state mutation:

- `execution_phase=V3_CANARY_EXECUTION`, `source_scope_phase=V3_IMPLEMENTATION_OFFLINE_FIRST`, and `request_phase=CANARY`;
- exact frozen scope SHA, sample-manifest path and SHA, `selected_document_ids=["S01"]`, source-review receipt SHA, and the accepted runtime-binding evidence path/SHA;
- `expected_runtime_identity` equal to the old accepted runtime/model/runtime-limits/request-policy/configuration hashes and paths, current independently reviewed local source hashes, and previously pinned external helper hashes;
- first-chunk execution sets `selected_chunk_indices=[1]`, `reusable_chunk_indices=[]`, and `first_chunk_acceptance_receipt_sha256=null`; every other chunk is `NOT_RUN` and the document stays `PARTIAL`;
- continuation selects a contiguous range starting at chunk 2, sets `reusable_chunk_indices=[1]`, and binds the exact hash of `/Users/lexi/Desktop/学习/agents调试/V4_PDF_RESEARCH_V3_SAMPLE_20261018_R1/first-chunk-acceptance-receipt.json`;
- that receipt uses schema `v4.pdf_research_v3.chunk_acceptance.v1`, status `PASS`, and an independent reviewer. It binds S01, the frozen scope and manifest, source-review/runtime-evidence hashes, request-schema hash, source PDF SHA, chunk identity, and queue idempotency, input, raw-response, and validated-result SHA-256 values;
- `request_budget={"maximum_model_calls":16,"max_attempts_per_chunk":1,"max_source_characters_per_chunk":8000,"max_serialized_request_envelope_bytes":32768,"automatic_resume":false}`;
- exact isolated research `write_allowlist`, independent queue root, and shared model-lock path; OCR, download, PDF lookup, production, BUY-gate updates, and orders are all false.

The prior source review receipt remains immutable but does not cover this candidate's changed hashes. A new independent source review must return `PASS` for the exact current hashes of all seven canonical source/test/README files before a refreshed execution-scope receipt can match.

## Request bounds

Every analyzed chunk contains at most 8,000 aggregate source-text characters. The actual serialized request envelope includes the system and user messages, JSON schema, model/profile/tool controls, and completion-token setting; its UTF-8 serialized size must be at most 32,768 bytes. Its byte count and SHA are persisted with the queue payload. Oversized source units are split at Unicode codepoint boundaries, and every source page must reconstruct exactly before chunk analysis. This deterministic byte envelope does not claim an exact tokenizer count or model-context fit; those remain `CANNOT_CONFIRM` until a separately authorized model response is reviewed. The S01 canary call budget is 16, with one queue attempt per selected chunk and no automatic retry/resume.

## Chunk failure stop and partial receipts

The offline R2 repair stops the document loop after any queue outcome other than `SUCCEEDED`, a missing or unreadable validated result, a request-preparation/binding-guard failure, or a queue/request exception. It does not enqueue or run later chunks after that stop point. Validated earlier chunks stay in `chunk_results`; the current attempted chunk is recorded as failed or unresolved, and untouched later chunks are listed separately as `NOT_RUN`.

The result and persisted receipt expose `coverage.chunk_execution` with selected and reused indices, total/completed/failed/unrun counts and IDs, detailed failed and unrun records, and a `stop_reason`. An incomplete analysis is `document_status=PARTIAL` and `coverage.full_analysis_complete=false`; chunks outside the current selection are `NOT_RUN`, never failed. Each chunk ID combines the document ID, four-digit chunk index, and source chunk SHA-256. Runtime-binding drift detected before enqueue records a stop reason and leaves the current and later chunks unrun while retaining prior successes.

Continuation may reuse chunk 1 only when the separate independent acceptance receipt binds it and the isolated queue contains that exact successful job. The reader verifies the same identity key and full input bytes, one successful attempt, raw-response and validated-result hashes, then re-parses and revalidates the raw response against the current schema and exact page slices. A mismatch stops before any new enqueue. Chunk selection is execution control only and is absent from the request body and content fingerprint.

The response-contract candidate remains offline until a new independent source review returns PASS and the parent freezes an execution-scope v2 receipt. No model request, API identity GET, OCR, download, or execution-scope activation has occurred during this repair.

## Evidence rules

- Every extracted code mention retains its literal code, stated market, nearby literal currency tokens (without attributing them to the security), page number, page offsets, and quote. Master validation remains `NOT_CHECKED_NO_MASTER_INPUT`.
- A same-market source contradiction is recorded as `UNRESOLVED` / `CANNOT_CONFIRM_CONFLICTING_CODES_WITHIN_MARKET`, with all code locations. Different market codes are kept separate; without an authoritative cross-market relationship map they remain `UNRESOLVED` / `CANNOT_CONFIRM_NO_AUTHORITATIVE_CROSS_MARKET_MAP`, not an asserted code error or dual listing.
- Numeric strings retain their original text and source range; conversions are not performed. For the raw-value presence check only, runs of Unicode whitespace collapse to one ASCII space. The stored model `raw_value_text` is not rewritten, and the source quote remains byte-for-byte derived from the original page slice; digits, signs, punctuation, units, currencies, and periods are not normalized. The model returns only a supplied `source_unit_id`; it cannot submit page numbers, quotes, or character offsets. The program derives the full verbatim source-unit slice, page offsets, and `quote_sha256` from the original page text, then requires exact slice equality. Unknown, foreign, out-of-chunk, or extra legacy quote/offset fields fail closed. All chunks must reconstruct every page's complete text before a document can be marked complete.
- `REPORT_SUBJECT` is distinct from `SUPPLIER`, `CUSTOMER`, and `AUTHOR_OR_INSTITUTION`. The prompt asks the model to classify mixed-table columns and cells independently using report date, headers, explicit actual/estimate/forecast markers, and wording; report genre does not set fact nature, and a past period alone does not prove a published actual. It requests adjacent comparison values and qualifiers, and has the model assign short descriptive fact labels internally before mapping links to the schema's existing array indices. Unresolved source meaning stays `UNKNOWN`; schema and output fields remain unchanged. Scheduled events stay in `verification_events`.
- Existing OCR text may be used only as an already-materialized cache fallback after native PDF text extraction. No OCR is invoked, and cache OCR visual quality remains `CANNOT_CONFIRM_NOT_VISUALLY_REVIEWED`.
- Results remain `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false`.

## Focused verification

Prior engineering baseline, before this semantic repair:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/pdf-v3-c1-final-pyc .venv/bin/python -m pytest -q -p no:cacheprovider --basetemp=/tmp/pdf-v3-c1-final tests/test_local_document_model.py tests/test_pdf_research.py tests/test_pdf_research_sample_cli.py
```

That baseline run returned `44 passed`. This semantic-repair writer run separately targets `tests/test_pdf_research.py`; its result and the revised prompt-envelope measurement are recorded in `semantic-repair-candidate.json`. These checks do not substitute for independent review of this candidate.

Independent reviewer rerun and `BEHAVIOR_VERIFIED` are still pending. This handoff does not claim that the repaired response contract has been model-executed, that S01 has been analyzed, or that a model result is accepted.
