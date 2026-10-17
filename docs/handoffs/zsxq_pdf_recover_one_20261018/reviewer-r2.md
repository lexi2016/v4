# Independent recover-one re-review (R2)

**PASS within the frozen offline review scope.** `REVIEWED`; focused `TESTED`; `BEHAVIOR_VERIFIED=PASS` (offline). `RECOVERED=NOT_RUN` as required.

The revised candidate closes the R1 P1. I rechecked the changed recovery gate and continuation checkpoint checks, reran the original bypass repro, and ran the three directly affected tests. The earlier R1 `FAIL` receipt and repro remain intact.

| Path | Frozen baseline SHA-256 | Revised candidate SHA-256 |
|---|---|---|
| `infrastructure/zsxq_pdf_ingestion.py` | `727a3f6cfcef626d6cf482eebf9e8d66418fcbe9817ae2e1dd1943c88e8384e0` | `5dedf912a9cc8b41646a5cfb0133ded4dbaa0168aae74157e75e4498cd1fd915` |
| `tests/test_zsxq_pdf_ingestion.py` | `8c3012d0e1d5cb2d6816a8afcf2bb922fa9bef97935f755477bbfe41f4a85a6d` | `27fb218b81427ef5904213d7c1951dd9004bf00693537b4f8d7d6154778eead9` |
| `ops/run_zsxq_hourly_delta.py` | `7260f1342ee2ee6d00373df330561fc093f1f176875759623143bff2e517531d` | `67892d233248c2e5cc7387b93fe228ab3f04c030c29719f41fb25ebc596aeff6` |

The normal complete-enumeration branch now calls `_require_active_recovery_claim` while holding the existing kernel lock and before it writes the processing index or reaches processing callbacks ([gate at line 1795](/Users/lexi/Desktop/学习/v4_app/infrastructure/zsxq_pdf_ingestion.py:1795)). The validation binds the marker, authorization audit, and consumed-index copies to the same document, authorization, source signature, claim status, and checkpoint state. For continuation it additionally requires the checkpoint to be cleared, a well-formed consumed checkpoint digest shared by all three records, and a recorded continuation count and start time ([claim validation at line 616](/Users/lexi/Desktop/学习/v4_app/infrastructure/zsxq_pdf_ingestion.py:616)). `_consume_recovery_checkpoint` writes that digest to the three copies before processing proceeds.

The original isolated repro now exits before the unclaimed request can process the target: `REPRO_REJECTED: PDF_RECOVERY_CLAIM_INCOMPLETE`. The new regression asserts metadata, URL, download, and OCR callbacks stay unchanged and that neither an audit nor consumed entry is created. The continuation regression also rejects a direct unconsumed continuation and a mismatched digest before callbacks.

Commands and results:

- `PYTHONPATH=. uv run --offline pytest -q tests/test_zsxq_pdf_ingestion.py -k 'process_pdf_batch_rejects_unclaimed_recovery_id or recovery_continuation_requires_consumed_checkpoint or recover_one_long_pdf_uses_safe_two_page_checkpoints' --basetemp=/tmp/v4-zsxq-pdf-recovery-review-r2/basetemp` → **3 passed, 39 deselected**, one existing Starlette/httpx deprecation warning.
- `PYTHONPATH=. uv run --offline python - <<'PY' ... runpy.run_path(repro_claim_bypass.py) ... PY` → **REPRO_REJECTED: PDF_RECOVERY_CLAIM_INCOMPLETE**; the wrapper asserts that exact refusal code.
- `uv run --offline python -m json.tool reviewer/verdict-r2.json` → PASS.

The writer reports 42 module tests passing on these candidate hashes; I did not independently rerun the full module suite in this R2 turn. The independently rerun regression subset covers the repaired direct bypass, the consumed-checkpoint gate, and the real `recover_one_pdf` long-document continuation path. No live API, download, OCR, queue, source index, service, or release was touched. Live recovery, source-index readback, runtime/API/UI behavior, and GitHub sync remain `NOT_RUN` or `CANNOT_CONFIRM` outside this reviewer scope.

No production source or tests were changed by the reviewer. R2 evidence is separate from the preserved R1 artifacts.
