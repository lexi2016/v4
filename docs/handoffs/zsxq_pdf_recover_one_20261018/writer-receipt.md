# Offline recover-one implementation receipt

State: `IMPLEMENTED` revised candidate; first independent review found one P1 and failed; the cited bypass is repaired and its offline repro now refuses the request. Independent re-review and repository sync remain pending; real recovery is `NOT_RUN`.

## Frozen scope and baseline

- Source root: `/Users/lexi/Desktop/学习/v4_app`.
- Baseline HEAD and branch: `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`, `codex/system-consolidation-20260912`.
- Frozen target `zsxq_pdf_ingestion_index.json` SHA-256: `3f279b93b48c13ed32651292b7a72339f8a19712bae731de3277f924e1141239`. This is the frozen data-index reference, not the Git index. No live data index was read or written in this batch.
- Exact pre-batch file SHA-256 values: module `727a3f6cfcef626d6cf482eebf9e8d66418fcbe9817ae2e1dd1943c88e8384e0`; tests `8c3012d0e1d5cb2d6816a8afcf2bb922fa9bef97935f755477bbfe41f4a85a6d`; ops `7260f1342ee2ee6d00373df330561fc093f1f176875759623143bff2e517531d`.
- Source files changed, measured against those snapshots: `infrastructure/zsxq_pdf_ingestion.py` (+1034/−12 lines), `tests/test_zsxq_pdf_ingestion.py` (+508/−0), and `ops/run_zsxq_hourly_delta.py` (+42/−1). The test and module remain untracked as they were before this batch; ops remains modified. None of these target paths is staged.
- The target paths are not staged. No Git index mutation was made.

## Implementation

`recover_one_pdf` validates the full 64-character document key, date, source run, existing source enumeration, its stored four-file input SHA map, the source metadata row, and the exhausted engine run before API/download/OCR callbacks. It selects by `document_key`; the queue and ordinary batch path refuse to advance a consumed recovery document.

The initial command records `AUTHORIZED`, then durably claims the event under the existing kernel lock with a per-document marker, the processing index, and the audit file. Processing starts only after the claim commits. Audit and consumed binding copies fail closed if any one is missing or inconsistent. Recovery preserves `attempts=2` and always uses the existing two-page batch limit, source metadata checks, HTTPS URL and redirect validation, PDF size/magic checks, verified PDF cache, OCR cache, and receipt paths.

`PARTIAL` results create a checkpoint only after the PDF, page file, and receipt verify against their hashes. Bounded continuation uses the same authorization ID, consumes the checkpoint before processing, verifies the current artifact again, and does not reauthorize or redownload a verified partial PDF. A crash, missing checkpoint, ambiguous commit, invalid artifact, or incomplete audit/index/guard write returns `CANNOT_CONFIRM` and consumes the recovery event. `READY`, `FAILED_FINAL`, and `CANNOT_CONFIRM` are terminal. The global `MAX_ATTEMPTS` stays `2`; no parser change was made.

The CLI seam adds `--pdf-recover-one` and `--pdf-recovery-continue`, both requiring `--date`, `--source-run-id`, `--pdf-document-key`, and `--pdf-authorization-id`. The source slot is read from the exact stored source binding.

## Reviewer finding and repair

The first independent review is preserved at `reviewer/verdict.md` with its exact repro at `reviewer/repro_claim_bypass.py`. It found that complete enumeration trusted a nonempty `_recovery_authorization_id` without checking durable claim records. The pre-fix repro returned `READY` after metadata/download/OCR callbacks with no audit row or consumed index entry.

The complete-enumeration path now verifies the exact active claim under the existing kernel lock before writing the processing index or invoking processing callbacks. Continuation additionally requires the prior checkpoint to be absent from all current-state copies and its consumed SHA-256 to match across the claim marker, authorization audit, and processing index. The checkpoint digest is persisted when the verified checkpoint is consumed. An unclaimed ID or mismatched durable state now fails closed before metadata/download/OCR.

## Verification

Runtime: `.venv/bin/python3`, Python `3.14.6`, macOS `26.6.2 arm64`.

Focused regression command:

```text
PYTHONPATH=. uv run --offline pytest -q tests/test_zsxq_pdf_ingestion.py -k 'process_pdf_batch_rejects_unclaimed_recovery_id or recovery_continuation_requires_consumed_checkpoint or recover_one_long_pdf_uses_safe_two_page_checkpoints' --basetemp=/tmp/v4-zsxq-pdf-recovery-p1-final/basetemp
```

Result: `3 passed, 39 deselected, 1 warning`.

The reviewer repro was first run before the repair and returned `batch_status=READY`, callbacks `metadata=3,url=3,download=3,ocr=2`, `authorization_audit_exists=false`, and `recovery_consumed_entry=null`. After the repair it was rerun in an exception-checking wrapper and returned `REPRO_REJECTED: PDF_RECOVERY_CLAIM_INCOMPLETE`.

Final focused-module command:

```text
PYTHONPATH=. uv run --offline pytest -q tests/test_zsxq_pdf_ingestion.py --basetemp=/tmp/v4-zsxq-pdf-recovery-p1-final/full
```

Result: `42 passed, 1 warning in 2.58s`. The warning is the existing Starlette deprecation for importing `TestClient` with `httpx`. Recovery tests use temporary roots and fake callbacks. The CLI integration test calls the real recovery entry through `ops.main`, with metadata/download/OCR callbacks replaced by local fakes. No live API, download, OCR, queue, source index, service, or release was touched.

One earlier targeted run omitted `--basetemp`; its three tests reached `[100%]`, but pytest exited nonzero while cleaning an unrelated stale protected temp directory. The isolated `--basetemp` rerun above passed.

Syntax check command:

```text
uv run --offline python -c 'import ast,pathlib; [ast.parse(pathlib.Path(p).read_text()) for p in ["infrastructure/zsxq_pdf_ingestion.py","tests/test_zsxq_pdf_ingestion.py","ops/run_zsxq_hourly_delta.py"]]; print("AST parse PASS")'
```

Result: `AST parse PASS`.

Current source SHA-256: module `5dedf912a9cc8b41646a5cfb0133ded4dbaa0168aae74157e75e4498cd1fd915`; tests `27fb218b81427ef5904213d7c1951dd9004bf00693537b4f8d7d6154778eead9`; ops `67892d233248c2e5cc7387b93fe228ab3f04c030c29719f41fb25ebc596aeff6`.

## Inactive invocation and rollback boundary

This template was **not executed**. It is for a later, separately authorized recovery against the controlled data root:

```text
PYTHONPATH=. uv run --offline python ops/run_zsxq_hourly_delta.py \
  --data-root <controlled-data-root> \
  --date 20261017 \
  --source-run-id 20261017_130000_130000125862 \
  --pdf-recover-one \
  --pdf-document-key 0273668ed1af2435f2a73167ac5282e1dfecd92b9b63e4dbfe873a07719ff684 \
  --pdf-authorization-id <unique-operator-approved-id>
```

For a clean `PARTIAL` checkpoint, replace `--pdf-recover-one` with `--pdf-recovery-continue` and reuse the same document key, date, source run, and authorization ID. An interrupted or uncertain claimed operation has no continuation checkpoint and cannot be retried under a new ID.

Rollback is limited to restoring these three exact source paths to the supplied `baseline/` bytes. No rollback was performed. No live authorization record was generated, no commit or push was made, and no runtime release was changed.

## Remaining gates

- Independent Luna Max Reviewer: `PENDING` for this repaired candidate; the earlier `FAIL` and repro remain in `reviewer/`.
- GitHub commit/push and remote readback: `NOT_DONE` under the parent instruction not to commit or push; the scope PASS_SIGNAL's sync portion is therefore `CANNOT_CONFIRM` and must be resolved by the controller.
- Frozen target recovery result: `NOT_RUN`; source-index readback is also `NOT_RUN` by design.
