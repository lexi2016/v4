# Incremental independent review R2: OVERSOLD partial-capture recovery

`REVIEWED=PASS_CANDIDATE` · `TESTED=PASS` · `BEHAVIOR_VERIFIED=PASS_CANDIDATE` · `DEPLOYED=NOT_DEPLOYED` · `NATURAL_SLOT_UNVERIFIED`

P0: 0 · P1: 0 · P2: 0

This review covers the R1 partial-return finding and the authorized TDX61 catalogue-cache recovery hunk only. The R1 P2 is resolved: partial captures are retried only when unresolved rows are accompanied by explicit transport evidence, and the existing TDX61 owner refreshes only a cached partial catalogue carrying a recognized connection/timeout error. Stable partial catalogues remain cached; retry exhaustion preserves and submits the partial result. The rest of the scheduler/lane merge was not re-reviewed. The earlier isolated API store/schema compatibility result remains applicable; this review made no API-side change.

## Owner error evidence reaches the retry classifier

The actual owner capture/reader/inspector path was exercised with the focused fixture's fake TDX API and a partial catalogue whose page failure is `TimeoutError`. The owner returned `ready_count=0`, `unassessed_count=1`; the unresolved record itself had `ValueError: TDXPY_SECURITY_MARKET_IDENTITY_UNKNOWN`, while the catalogue stored the actual `TimeoutError` in `coverage_gaps[].error`. `OversoldDaily._inspect_capture` returned the manifest, records, catalogues, failed catalogues, and refresh events; `_retryable_partial_transport` classified the capture as retryable with `scope=CATALOGUE`. This verifies the exact owner-to-orchestrator evidence shape that the R1 regression missed. The fixture made no network call and wrote only temporary artifacts.

The code path is consistent with that evidence: the owner converts endpoint exceptions into per-record errors and `failed_catalogues`, and partial catalogue-page failures remain in `catalogues[].coverage_gaps`; the orchestrator checks both forms ([owner cache branch](/Users/lexi/Desktop/学习/v4_app/upstreams/v3_shared_data/shared_data/hk_daily_supplement.py:1056), [owner error recording](/Users/lexi/Desktop/学习/v4_app/upstreams/v3_shared_data/shared_data/hk_daily_supplement.py:1120), [classifier](/Users/lexi/Desktop/学习/v4_app/v4/manager_workbench/oversold_daily.py:45), [capture decision](/Users/lexi/Desktop/学习/v4_app/v4/manager_workbench/oversold_daily.py:304)).

## Cache recovery and bounded outcomes

The owner regression starts with a cached partial catalogue containing a timeout, then returns a complete refresh. It verifies that the old exact bytes are archived under their SHA, the replacement cache references and validates that archive, the second capture becomes ready, and the normal owner reader accepts the new manifest. A separate regression verifies that a stable `ValueError` partial catalogue is not fetched again ([owner cache tests](/Users/lexi/Desktop/学习/v4_app/upstreams/v3_shared_data/tests/test_hk_daily_supplement_tdxpy61.py:161)).

The scheduler regressions now cover a normal returned partial with transport evidence retrying before submission, a stable `ValueError` quarantine submitting without another capture, and transport partial output being retained and submitted after retry exhaustion ([scheduler tests](/Users/lexi/Desktop/学习/v4_app/tests/manager_workbench/test_oversold_daily_scheduler.py:250)). I found no remaining P0/P1/P2 issue in this incremental scope.

## Validation and limits

- Re-ran `.venv/bin/python -m pytest -q --tb=short --basetemp=/tmp/pytest-oversold-daily-review-r2 tests/manager_workbench/test_oversold_daily_scheduler.py upstreams/v3_shared_data/tests/test_hk_daily_supplement_tdxpy61.py` — **13 passed in 0.14s**.
- `python3 docs/handoffs/oversold_daily_automation_20261016/prepare_runtime_candidate.py --check` — `CANDIDATE_CHECK_PASS; runtime preimages match; NOT_DEPLOYED`.
- `python3 docs/handoffs/oversold_daily_automation_20261016/verify_runtime_delta.py` — `STAGED_RUNTIME_DELTA_PASS; all 6 outputs match candidate SHAs`.
- Workspace implementation files match the six prepared candidate artifacts except the already documented unrelated `history_resolution_proof` hunk in workspace `source_bindings.py`; that hunk is absent from the runtime candidate. The new owner file matches its candidate SHA.
- No deploy, live TDX request, active-state write, or formal run was performed. Live catalogue refresh, HTTP/API endpoint and UI readback, and natural scheduled execution remain `CANNOT_CONFIRM`; the previously isolated API store/schema compatibility PASS is unchanged. Full deployed acceptance therefore remains open.
