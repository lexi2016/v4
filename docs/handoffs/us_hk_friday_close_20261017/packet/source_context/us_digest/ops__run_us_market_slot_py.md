## Source excerpt: `ops/run_us_market_slot.py`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/futu-industry-us-20261016-r1/app/ops/run_us_market_slot.py`

Original full-file SHA-256: `0244fd5e717b3977e5d227b6084fd12eb77f2ebef6802be629b2761596e2f79e`

Release/worktree group: `us_digest`

US slot request assembly, dispatch invocation, typed failure payload, and CLI business-date binding.

### Full-source lines 131-151

```python

def _request_for_slot(
    *,
    business_date: str,
    slot: str,
    calendar: Any = None,
) -> DispatchRequest:
    if calendar is None:
        dates = compute_dates(business_date=business_date, slot=slot)
    else:
        dates = compute_dates(
            business_date=business_date,
            slot=slot,
            calendar=calendar,
        )
    return DispatchRequest(
        scheduled_date=dates["scheduled_date"],
        business_date=dates["business_date"],
        target_date=dates["target_date"],
        slot=slot,
        mode=DispatchMode.LIVE,
    )

```

### Full-source lines 339-396

```python

def run_us_market_slot(
    *,
    data_root: Path | str,
    ledger_root: Path | str,
    slot: str,
    business_date: str,
    timeout_seconds: float = 600.0,
    dry_run: bool = False,
    calendar: Any = None,
    catalog: RuntimeCatalog | None = None,
    executor: Callable[..., Any] | None = None,
    ledger: ExecutionLedger | None = None,
) -> dict[str, Any]:
    """Run one US-only dispatch using the existing V4 runtime components.

    ``executor`` and ``ledger`` are optional seams for isolated tests.  Normal
    callers leave them unset so the fixed registry and the supplied V4 ledger
    root are used.  A dry run is delegated to ``dispatch_due``; its existing
    dry-run namespace keeps claims and receipts out of the authoritative root.
    """

    selected_slot = _validate_slot(slot)
    timeout = _timeout(timeout_seconds)
    request = _request_for_slot(
        business_date=business_date,
        slot=selected_slot,
        calendar=calendar,
    )
    selected_catalog = select_us_catalog(catalog)
    data_path = Path(data_root)
    ledger_path = Path(ledger_root)
    dispatch_executor = executor
    if dispatch_executor is None:
        dispatch_executor = FixedExecutorRegistry(
            data_root=data_path,
            timeout_seconds=timeout,
            repo_root=Path(__file__).resolve().parents[1],
        )
    dispatch_ledger = ledger if ledger is not None else ExecutionLedger(ledger_path)
    retry_context = (
        None
        if dry_run
        else _failed_close_retry_context(
            ledger=dispatch_ledger,
            business_date=request.business_date,
            retry_slot=selected_slot,
        )
    )
    if retry_context is not None:
        dispatch_executor = _RetryAwareExecutor(dispatch_executor, retry_context)
    receipt = dispatch_due(
        request,
        selected_catalog,
        dispatch_executor,
        ledger=dispatch_ledger,
        dry_run=bool(dry_run),
    )
    payload = receipt.to_dict()

```

### Full-source lines 418-435

```python

    *, slot: str, business_date: str | None, reason: str, dry_run: bool
) -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA,
        "dispatch_schema_version": None,
        "status": "FAILED",
        "mode": DispatchMode.LIVE.value,
        "slot": slot,
        "business_date": business_date,
        "scheduled_date": business_date,
        "target_date": business_date,
        "selected_workload_ids": [],
        "started_workload_ids": [],
        "workload_results": [],
        "receipt_path": "",
        "reason": reason,
        "owner_id": US_MARKET_OWNER_ID,
        "workload_id": US_MARKET_WORKLOAD_ID,

```

### Full-source lines 443-484

```python

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the registered V4 US market workload for one Shanghai slot"
    )
    parser.add_argument(
        "--slot",
        help="Shanghai HHMM; only 0415, 0515, 2100, and 2200 are accepted (default: latest elapsed slot, within 15 minutes)",
    )
    parser.add_argument("--date", help="Shanghai business date YYYYMMDD (default: today Shanghai)")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--ledger-root", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    now = datetime.now(SHANGHAI)
    slot = args.slot if args.slot is not None else now.strftime("%H%M")
    business_date = args.date or now.strftime("%Y%m%d")
    try:
        if args.slot is None:
            slot = _default_slot_for_time(now)
        result = run_us_market_slot(
            data_root=args.data_root,
            ledger_root=args.ledger_root,
            slot=slot,
            business_date=business_date,
            timeout_seconds=args.timeout_seconds,
            dry_run=args.dry_run,
        )
    except Exception as error:  # CLI boundary must fail closed and emit JSON.
        reason = f"{type(error).__name__}: {error}"
        print(f"US market slot failed: {reason}", file=sys.stderr)
        result = _failure_payload(
            slot=slot,
            business_date=business_date,
            reason=reason,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") in ZERO_EXIT_STATUSES else 1

```
