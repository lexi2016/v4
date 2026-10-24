# Reviewed stream heartbeat repair

Only `infrastructure/local_document_model.py` and `tests/test_local_document_model.py` changed. The adapter recognizes the installed oMLX content-free keepalive SSE shape, preserves raw bytes and strict genuine model identity checks, and does not refresh substantive progress. No prompt/schema/model/sampling/configuration change.

| Path | Before SHA256 | After SHA256 |
|---|---|---|
| infrastructure/local_document_model.py | 9021f1826b329f9db3d6ecf8d6c9a37b024cac1a80207b963e2ba8063a813d57 | fbef2ed55b8116c8a3a68ef4f0c1c9849420c3460ecb17772f792af8618633ad |
| tests/test_local_document_model.py | ba2d8c6b095ed20848f67a0ea1249f6235f6b081579ff0cf2fafaf8453c92d9d | b0043daf5fa2b096d5696576c2733e73eafab212c122303ad50af5e7605f6ee7 |

Independent focused verification: 38 passed,7 deselected, network blocked, zero real POSTs during tests. Receipt SHA3f764f7a243a01aa86c812cf7083f577f5df107a13d068f1082b707ca7b1a56c. Patch SHA461d94551a71ba54ed1fdfbe92b79213560b9e3ef6d3a12bb52750835da2e60e. Unchanged API/UI/Task1/execution suites reused.

The two unconsumed fixed real samples each used exactly one POST through the existing reviewed executor/shared gate. Both complete raw answers were persisted. Program validation returned CONTENT_FAILED: FULL_NUMERIC_BOUND_LOST and FULL_NUMERIC_VALUE_NOT_IN_QUOTE. Original first sample remains a consumed transport failure and was never retried. No accepted content receipt and no20 expansion. Independent content verdicts remain separate from code PASS.

Only reviewed source/tests/this compact result may be synchronized by root. PDFs, prepared texts, exact requests, raw streams, outputs and runtime data stay local. Writer did not commit/push/deploy or alter healthy services/settings.

Final independent content receipt SHA91ac8f495a698bc0a892e7835c2a908cf5b48a20873faa01da5d3510840530b8 records mixed causes: known OCR and split decimal input, a validator false rejection of correct166.0 (same layout10.40), structured bound semantics, max5 fact/forecast budget with prompt/model coverage contribution inseparable, and observed unsupported source citations. Zero full-contentPASS. This is not a model-only capability conclusion. The two reviewed source/test files were remotely read back at4b777f9c8552fe6158b049b16875ee7ac3bbbb49; no local input/output was uploaded.
