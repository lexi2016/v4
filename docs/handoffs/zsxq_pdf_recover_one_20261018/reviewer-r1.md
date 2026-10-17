# Independent recover-one review

**Verdict: FAIL — `REVIEWED`; `TESTED` (offline); `BEHAVIOR_VERIFIED=FAIL` (offline).** The real recovery remains `NOT_RUN` as required.

I reviewed the candidate against the three exact baseline copies in `baseline/`. Their SHA-256 values match `baseline.json`; candidate SHA-256 values also match the writer receipt:

| Path | Baseline SHA-256 | Candidate SHA-256 |
|---|---|---|
| `infrastructure/zsxq_pdf_ingestion.py` | `727a3f6cfcef626d6cf482eebf9e8d66418fcbe9817ae2e1dd1943c88e8384e0` | `92cb62710cf53f335dff7a794dbad3be3d5a887f46e32308eebca0abd15f2640` |
| `tests/test_zsxq_pdf_ingestion.py` | `8c3012d0e1d5cb2d6816a8afcf2bb922fa9bef97935f755477bbfe41f4a85a6d` | `9e9d965564d82f6c6997dcc9141becfb65ba667a5b81d979cb2cc061ce322aa2` |
| `ops/run_zsxq_hourly_delta.py` | `7260f1342ee2ee6d00373df330561fc093f1f176875759623143bff2e517531d` | `67892d233248c2e5cc7387b93fe228ab3f04c030c29719f41fb25ebc596aeff6` |

## P1 finding

`process_pdf_batch` can bypass the durable one-time claim by accepting any nonempty `_recovery_authorization_id`. Claim validation occurs only in its incomplete-source-enumeration branch at [infrastructure/zsxq_pdf_ingestion.py](/Users/lexi/Desktop/学习/v4_app/infrastructure/zsxq_pdf_ingestion.py:1686). On the normal complete-enumeration path, the function selects the requested document and checks only `FAILED`/`PARTIAL` plus `attempts == MAX_ATTEMPTS` at lines 1818–1830, then passes `recovery_claimed=True` at line 1957. `_process_one` consequently bypasses the exhausted-attempt guard at line 1273 without any audit, claim marker, or consumed-index record.

The isolated repro at [repro_claim_bypass.py](/Users/lexi/Desktop/学习/agents调试/V4_ZSXQ_RECOVER_ONE_20261018_R1/reviewer/repro_claim_bypass.py) calls that path with a fake `unclaimed-id` and local-only callbacks. It returned `batch_status=READY`, recorded callback activity, and reported both `authorization_audit_exists=false` and `recovery_consumed_entry=null`. This violates the frozen claim invariant and permits bypass of one-time recovery state through the module API. Whether any other runtime exposes this private parameter is `CANNOT_CONFIRM`; repository search found no other caller beyond `recover_one_pdf` and tests.

**Fix list:** Gate the complete-enumeration recovery path on a persisted exact claim under the existing kernel lock, including the consumed-checkpoint condition for continuation. Do not use a caller-provided nonempty ID as proof of a claim. Add a regression that calls `process_pdf_batch` without an existing claim and proves it refuses before metadata/download/OCR callbacks.

## Acceptance evidence

- Independent targeted rerun: `PYTHONPATH=. uv run --offline pytest -q tests/test_zsxq_pdf_ingestion.py --basetemp=/tmp/v4-zsxq-pdf-recovery-review-20261018/basetemp` → **40 passed, 1 existing Starlette/httpx deprecation warning**. The first invocation failed only because the requested basetemp parent did not exist; after creating that isolated temporary directory, the rerun passed.
- The suite covers exact document/date/run/source binding, two-page continuation with the same authorization, no redownload, replay/concurrency, failed OCR, verified cache reuse, unsafe URLs and redirects, write failures/interruption, missing audit entries, and the CLI selecting the exact key. Callback fakes keep the tests offline.
- Source inspection confirms the existing `MAX_ATTEMPTS=2` bound and existing processing/storage/cache path remain in use. The `recover_one_pdf` entry point commits claim records before it calls `process_pdf_batch`; the P1 finding is the alternate direct module path that skips that gate.
- CLI behavior in the candidate integration test is offline because the recovery entry is replaced with a fake-callback wrapper. The test does not exercise real API/download/OCR behavior. Real recovery, live source-index readback, runtime/API/UI behavior, and GitHub sync remain `NOT_RUN`/`CANNOT_CONFIRM` under this review scope.

No production source or test files were modified by the reviewer. The only added review artifacts are this verdict and the isolated repro script.
