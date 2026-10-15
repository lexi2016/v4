# OVERSOLD P2 cache-first transport repair receipt

Status: `IMPLEMENTED`; writer verification passed; independent review pending; `PREPARED_NOT_DEPLOYED`.

The existing TDX61 owner now validates exact per-security cache entries before connecting. It connects only for an exact cache miss, a missing catalogue, or a catalogue with an explicit retryable transport failure. A connector failure leaves verified READY cache records in the capture and attaches transport evidence only to unresolved requests. `ResponseHeaderRecvFails` is classified as transport; stable `ValueError` data-validation failures remain terminal. The scheduler permits one classifier-migration recovery only for the pinned 20261015→20261016 terminal cursor and old capture; it validates that old capture's manifest/raw hashes and transport evidence before recapturing. Capture/job counters and retry backoff remain cumulative, and the migration marker prevents a second terminal unlock.

Changed source and tests:

- `upstreams/v3_shared_data/shared_data/hk_daily_supplement.py`
- `v4/manager_workbench/oversold_daily.py`
- `upstreams/v3_shared_data/tests/test_hk_daily_supplement_tdxpy61.py`
- `tests/manager_workbench/test_oversold_daily_scheduler.py`

Focused tests:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q --tb=short --basetemp=/tmp/pytest-oversold-cache-first-writer upstreams/v3_shared_data/tests/test_hk_daily_supplement_tdxpy61.py tests/manager_workbench/test_oversold_daily_scheduler.py
18 passed in 0.17s
```

Exact local-data offline checks used temporary output roots and a fake connector that always fails. The HK.00001 canary validated its current exact cache hit, with zero connector calls, one READY row, and zero bar requests. The 689-code PANEL_GAPS consumer verified 567 exact existing cache files against the prior READY response SHAs, retained all 567 READY rows, and recorded 122 unresolved rows; it made zero bar requests and its produced manifest passed the owner reader. Both temporary output trees were discarded. These checks did not contact TDX or modify the authoritative cache.

The current r4 candidate is in `runtime_preimage_r4/`, `runtime_candidate_r4/`, and `runtime_exact_delta_r4.patch`; `runtime_exact_delta_r4.json` pins base release `zsxq-pdf-ocr-scheduler-20261016-r4`, release manifest SHA `4710696eb61e60ac5dbd1ea56aa2e7a3762d9c1f9170d206b4dc0beac4769e91`, and only the two changed runtime files. `prepare_runtime_delta_r4.py --prepare` returned `R4_RUNTIME_DELTA_CHECK_PASS`; the candidate remains not deployed.

`CANNOT_CONFIRM`: independent reviewer verdict for this new delta; live scheduler recovery against the cursor; live TDX behavior; API/UI readback; natural scheduled result. No active release file, service, cursor, old run, plan, API, or UI was changed by this repair or candidate preparation.
