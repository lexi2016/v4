"""ops.run_v35_macos_scheduler: cli_entry (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _main_body(_v4_scope, /, argv):
    parser = _v4_global(_v4_scope, 'argparse').ArgumentParser(description="Run the due fixed V3.5 macOS slot")
    parser.add_argument("--data-root", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--ledger-root", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--shared-data-root", type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--hk-universe-root", type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--shared-package-root", type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--selector-data-root", type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--preselection-input-root", type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--stage-selection-root", type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument(
        "--hk-0-2-python",
        type=_v4_global(_v4_scope, 'Path'),
        default=(
            _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'os').environ["V35_HK_0_2_PYTHON"])
            if _v4_global(_v4_scope, 'os').environ.get("V35_HK_0_2_PYTHON")
            else None
        ),
    )
    parser.add_argument("--timeout-seconds", type=_v4_global(_v4_scope, 'float'), default=600.0)
    parser.add_argument("--slot", choices=_v4_global(_v4_scope, 'ALL_SLOTS'), help="fixed-slot canary override")
    parser.add_argument("--date", help="YYYYMMDD canary date; requires --slot")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--manager-capture-only", action="store_true", help=_v4_global(_v4_scope, 'argparse').SUPPRESS)
    parser.add_argument("--release-id", default=_v4_global(_v4_scope, 'os').environ.get("V35_RELEASE_ID", ""))
    parser.add_argument("--upstream-fingerprint", default=_v4_global(_v4_scope, 'os').environ.get("V35_UPSTREAM_FINGERPRINT", ""))
    args = parser.parse_args(argv)
    if args.manager_capture_only and (args.slot or args.date or args.dry_run):
        parser.error("--manager-capture-only cannot combine with overrides")
    if args.date and not args.slot:
        parser.error("--date requires --slot")

    # launchd does not guarantee proxy variable casing for child processes.
    # Install the bounded research transport environment at this scheduler
    # boundary so hourly peripheral executors inherit the same proxy-first,
    # loopback-direct policy as the shared-stage child.
    _v4_global(_v4_scope, 'os').environ.update(_v4_global(_v4_scope, 'build_proxy_environment')(_v4_global(_v4_scope, 'os').environ.copy()))

    detected_date, detected_slot = _v4_global(_v4_scope, 'current_slot')()
    if args.slot:
        due = {
            "business_date": args.date or detected_date,
            "observed_slot": detected_slot,
            "slot": args.slot,
            "catchup": False,
            "lag_minutes": 0,
        }
    else:
        due = _v4_global(_v4_scope, 'resolve_due_slot')(
            ledger_root=args.ledger_root,
            capture_only=args.manager_capture_only,
            release_id=args.release_id or None,
            upstream_fingerprint=args.upstream_fingerprint or None,
        )
    if due.get("retry_blocked"):
        _v4_global(_v4_scope, '_emit')(
            {
                "schema_version": _v4_global(_v4_scope, 'RESULT_SCHEMA'),
                "status": "RETRY_BACKOFF",
                "capture_retry": due.get("capture_retry"),
                "business_date": due["business_date"],
                "observed_slot": due["observed_slot"],
                "slot": None,
                "catchup": {"applied": False, "lag_minutes": 0},
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
        return 0
    slot = _v4_global(_v4_scope, 'str')(due["slot"])
    business_date = args.date or _v4_global(_v4_scope, 'str')(due["business_date"])
    if slot not in _v4_global(_v4_scope, 'ALL_SLOTS'):
        _v4_global(_v4_scope, '_emit')(
            {
                "schema_version": _v4_global(_v4_scope, 'RESULT_SCHEMA'),
                "status": "NO_DUE_SLOT",
                "business_date": business_date,
                "observed_slot": due["observed_slot"],
                "catchup": {
                    "applied": False,
                    "lag_minutes": 0,
                },
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
        return 0

    shared_acquisition: dict[str, Any] = {
        "status": "NOT_STAGE_WORKLOAD_SELECTED",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    stage_gate_state: dict[str, Any] = {
        "attempted": False,
        "result": None,
        "failure": None,
    }

    def stage_workload_guard(workload, request, _decision):
        """Lazily gate only an actually selected Stage workload.

        The dispatcher remains responsible for workload selection and claims.
        This callback only memoizes the existing Stage prerequisite so a mixed
        dispatch cannot run it once per Stage workload or before an independent
        intraday workload.
        """

        nonlocal shared_acquisition
        workload_id = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'getattr')(workload, "workload_id", ""))
        if workload_id not in _v4_global(_v4_scope, 'STAGE_WORKLOAD_IDS'):
            return None
        if stage_gate_state["attempted"]:
            if stage_gate_state["failure"] is not None:
                failure = _v4_global(_v4_scope, 'dict')(stage_gate_state["failure"])
                failure["workload_id"] = workload_id
                raise _v4_global(_v4_scope, 'WorkloadExecutionError')(failure)
            return stage_gate_state["result"]

        stage_gate_state["attempted"] = True
        if _v4_global(_v4_scope, '_is_non_trading_day')(request.business_date):
            gate = {
                "status": "SKIPPED_NON_TRADING_DAY",
                "stage_workload_id": workload_id,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
            stage_gate_state["result"] = gate
            shared_acquisition = gate
            return gate

        try:
            if args.stage_selection_root is None:
                raise _v4_global(_v4_scope, 'ValueError')("STAGE_SELECTION_ROOT_MISSING")
            stage_acquisition_universe = _v4_global(_v4_scope, 'ensure_stage_candidate_input')(
                data_root=args.data_root,
                business_date=request.business_date,
            )
            consumed = _v4_global(_v4_scope, 'consume_shared_stage_selection')(
                business_date=request.business_date,
                slot=request.slot,
                selection_root=args.stage_selection_root,
                stage_acquisition_universe=stage_acquisition_universe,
            )
            selection_status = _v4_global(_v4_scope, 'str')(consumed.get("selection_status") or "CANNOT_CONFIRM").upper()
            if selection_status not in {"READY", "READY_EMPTY", "PARTIAL_WITH_ROWS"}:
                raise _v4_global(_v4_scope, 'RuntimeError')("STAGE_SELECTION_NOT_READY")
            unsafe = [
                field
                for payload in (stage_acquisition_universe, consumed)
                for field in ("production_allowed", "buy_gate_updated", "orders_sent")
                if payload.get(field) is not False
            ]
            if unsafe:
                raise _v4_global(_v4_scope, 'RuntimeError')("STAGE_SELECTION_UNSAFE")
            gate = {
                "status": "READY",
                "stage_workload_id": workload_id,
                "selection_status": selection_status,
                "stage_acquisition_universe": stage_acquisition_universe,
                "selection": consumed,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        except _v4_global(_v4_scope, 'Exception') as error:
            failure = {
                "status": "FAILED",
                "workload_id": workload_id,
                "modules": ["stage_gate"],
                "exit_code": 1,
                "reason": "STAGE_PRECONDITION_NOT_READY",
                "error_code": _v4_global(_v4_scope, 'type')(error).__name__.upper(),
                "failure_class": "UPSTREAM_NOT_READY",
                "attempt_state": "STAGE_GATE_FAILED",
                "cannot_confirm": ["STAGE_PRECONDITION_NOT_READY"],
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
            stage_gate_state["failure"] = failure
            shared_acquisition = failure
            raise _v4_global(_v4_scope, 'WorkloadExecutionError')(failure) from error

        stage_gate_state["result"] = gate
        shared_acquisition = gate
        return gate

    try:
        dates = _v4_global(_v4_scope, 'compute_dates')(business_date=business_date, slot=slot)
        result = _v4_global(_v4_scope, 'run_scheduled_slot')(
            data_root=args.data_root,
            slot=slot,
            business_date=dates["business_date"],
            scheduled_date=dates["scheduled_date"],
            target_date=dates["target_date"],
            ledger_root=args.ledger_root,
            shared_data_root=args.shared_data_root,
            hk_universe_root=args.hk_universe_root,
            shared_package_root=args.shared_package_root,
            hk_0_2_python_executable=args.hk_0_2_python,
            selector_data_root=args.selector_data_root,
            preselection_input_root=args.preselection_input_root,
            stage_selection_root=args.stage_selection_root,
            timeout_seconds=args.timeout_seconds,
            dry_run=args.dry_run,
            workload_guard=None if args.dry_run else stage_workload_guard,
        )
    except _v4_global(_v4_scope, 'Exception') as error:  # launchd boundary: always emit fail-closed JSON
        _v4_global(_v4_scope, '_emit')(
            {
                "schema_version": _v4_global(_v4_scope, 'RESULT_SCHEMA'),
                "status": "FAILED",
                "slot": slot,
                "business_date": business_date,
                "reason": f"{_v4_global(_v4_scope, 'type')(error).__name__}: {error}",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
        return 1

    _v4_global(_v4_scope, '_emit')(
        {
            **result,
            "macos_scheduler_schema_version": _v4_global(_v4_scope, 'RESULT_SCHEMA'),
            "shared_acquisition": shared_acquisition,
            "observed_slot": due["observed_slot"],
            "catchup": {
                "applied": _v4_global(_v4_scope, 'bool')(due["catchup"]),
                "lag_minutes": _v4_global(_v4_scope, 'int')(due["lag_minutes"]),
                "scheduled_slot": slot,
            },
        }
    )
    return 0 if result["status"] in _v4_global(_v4_scope, 'ZERO_EXIT_STATUSES') else 1
