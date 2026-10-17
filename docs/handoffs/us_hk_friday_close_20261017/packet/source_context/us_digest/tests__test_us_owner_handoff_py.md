## Source excerpt: `tests/test_us_owner_handoff.py`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/futu-industry-us-20261016-r1/app/tests/test_us_owner_handoff.py`

Original full-file SHA-256: `7112a09e9b61704d3c652cf00139c906365195cda9e55b95ccd2eab811321be3`

Release/worktree group: `us_digest`

Existing single-workload dispatch idempotency and fail-closed retry tests.

### Full-source lines 103-143

```python

def test_only_us_is_selected_and_repeat_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _bind_current_release(tmp_path, monkeypatch)
    calls: list[str] = []
    ledger_root = tmp_path / "dispatcher"

    first = us_slot.run_us_market_slot(
        data_root=tmp_path / "data",
        ledger_root=ledger_root,
        slot="2100",
        business_date="20260915",
        executor=_success_executor(calls),
    )

    assert first["status"] == "SUCCEEDED", first
    assert first["selected_workload_ids"] == [us_slot.US_MARKET_WORKLOAD_ID]
    assert first["started_workload_ids"] == [us_slot.US_MARKET_WORKLOAD_ID]
    assert calls == [us_slot.US_MARKET_WORKLOAD_ID]
    assert first["mode"] == DispatchMode.LIVE.value
    assert all(first[field] is False for field in (
        "production_allowed",
        "buy_gate_updated",
        "orders_sent",
    ))

    repeated = us_slot.run_us_market_slot(
        data_root=tmp_path / "data",
        ledger_root=ledger_root,
        slot="2100",
        business_date="20260915",
        executor=_success_executor(calls),
    )

    assert repeated["status"] == "CONCURRENCY_SKIPPED", repeated
    assert repeated["selected_workload_ids"] == []
    assert repeated["started_workload_ids"] == []
    assert calls == [us_slot.US_MARKET_WORKLOAD_ID]
    receipt_files = tuple(ledger_root.rglob("*.dispatch-receipt.json"))
    assert len(receipt_files) == 1
    stored = json.loads(receipt_files[0].read_text(encoding="utf-8"))
    assert stored["selected_workload_ids"] == [us_slot.US_MARKET_WORKLOAD_ID]


```

### Full-source lines 145-180

```python

def test_failed_us_dispatch_is_fail_closed_and_can_retry_its_released_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_current_release(tmp_path, monkeypatch)
    ledger_root = tmp_path / "dispatcher"

    def fail(_workload, _request, _decision):
        raise RuntimeError("fixture upstream unavailable")

    failed = us_slot.run_us_market_slot(
        data_root=tmp_path / "data",
        ledger_root=ledger_root,
        slot="0415",
        business_date="20260915",
        executor=fail,
    )

    assert failed["status"] == "FAILED", failed
    assert failed["selected_workload_ids"] == [us_slot.US_MARKET_WORKLOAD_ID]
    assert failed["started_workload_ids"] == []
    assert failed["workload_results"][0]["workload_id"] == us_slot.US_MARKET_WORKLOAD_ID
    assert all(failed[field] is False for field in (
        "production_allowed",
        "buy_gate_updated",
        "orders_sent",
    ))
    assert not (ledger_root / "claims" / "live" / "20260915" / "0415" / "dispatch.claim.json").exists()

    calls: list[str] = []
    recovered = us_slot.run_us_market_slot(
        data_root=tmp_path / "data",
        ledger_root=ledger_root,
        slot="0415",
        business_date="20260915",
        executor=_success_executor(calls),
    )

```
