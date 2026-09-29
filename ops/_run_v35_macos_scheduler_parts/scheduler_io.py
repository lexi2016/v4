"""ops.run_v35_macos_scheduler: scheduler_io (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __intraday_attempt_outcome_body(_v4_scope, /, observed):
    """Classify an intraday failure before release/upstream retry resets.

    A retry is safe only when the child explicitly persisted that no provider
    request was made.  A successful/ALREADY_EXISTS child is already complete;
    it must not block a retry of a failed sibling workload.  Missing, malformed,
    or contradictory attempt metadata remains unknown and blocks the scheduler,
    even if an unrelated release or upstream pointer changed.
    """

    aggregate_no_request = False
    saw_child = False
    saw_child_no_request = False
    saw_child_success = False
    for payload in observed:
        aggregate_failure = _v4_global(_v4_scope, 'str')(payload.get("failure_class") or "").strip().upper()
        if aggregate_failure == "INTRADAY_NO_REQUEST":
            aggregate_no_request = True
        elif aggregate_failure.startswith("INTRADAY_"):
            return "BLOCK"
        results = payload.get("workload_results")
        if not _v4_global(_v4_scope, 'isinstance')(results, _v4_global(_v4_scope, 'list')):
            continue
        for result in results:
            if not _v4_global(_v4_scope, 'isinstance')(result, _v4_global(_v4_scope, 'dict')) or result.get("workload_id") != "v4_intraday_research":
                continue
            saw_child = True
            state = _v4_global(_v4_scope, 'str')(result.get("attempt_state") or "").strip().upper()
            failure = _v4_global(_v4_scope, 'str')(result.get("failure_class") or "").strip().upper()
            status = _v4_global(_v4_scope, 'str')(result.get("status") or "").strip().upper()
            if status in {"SUCCEEDED", "ALREADY_EXISTS"}:
                # A completed child may have made a provider request.  Its
                # request-boundary state is therefore not evidence that the
                # failed Stage sibling must be blocked.  A terminal success
                # carrying failure/unknown/in-flight metadata is contradictory
                # and remains fail-closed.
                if (
                    failure
                    or result.get("error_code")
                    or state not in {"", "SUCCEEDED", "REQUEST_ATTEMPTED"}
                ):
                    return "BLOCK"
                saw_child_success = True
                continue
            if (
                state == "FAILED_NO_REQUEST"
                and failure == "INTRADAY_NO_REQUEST"
                and status in {"", "FAILED"}
            ):
                saw_child_no_request = True
                continue
            # A child result is the durable request-boundary fact.  Do not let
            # an aggregate INTRADAY_NO_REQUEST label override a sent,
            # in-flight, malformed, or otherwise inconsistent child result.
            return "BLOCK"
    if saw_child:
        if saw_child_success:
            # Do not let a successful intraday child suppress retry of a
            # retryable Stage sibling; the execution ledger retains the
            # completed child and prevents it from being run again.
            return "BLOCK" if aggregate_no_request or saw_child_no_request else None
        return "RETRY" if saw_child_no_request else "BLOCK"
    # An aggregate label without a matching explicit child state is not
    # sufficient evidence for a safe provider retry.
    return "BLOCK" if aggregate_no_request else None


def __is_non_trading_day_body(_v4_scope, /, business_date):
    """Return whether both stage markets are closed for the exact date.

    Stage candidate input is a prerequisite only on an eligible market day.
    The dispatcher remains the authority for the terminal result; this guard
    only prevents a non-trading date from invoking the prerequisite first.
    """

    states = _v4_global(_v4_scope, 'resolve_market_states')(_v4_global(_v4_scope, 'load_market_calendar')(), business_date)
    return _v4_global(_v4_scope, 'all')(
        states[key] is _v4_global(_v4_scope, 'TradingDayState').NON_TRADING_DAY
        for key in ("a_share", "hk_connect")
    )


def _run_shared_stage_acquisition_body(_v4_scope, /, *, business_date, slot, data_root, shared_data_root, shared_package_root, selector_data_root, timeout_seconds, process_runner, universe_materializer):
    """Acquire the fixed shared stage bundle before V3.5 materialization."""
    stage_id = _v4_global(_v4_scope, 'SHARED_STAGE_BY_SLOT').get(slot)
    if stage_id is None:
        return {"status": "NOT_STAGE_SLOT"}
    universe = universe_materializer(data_root, business_date)
    artifact = universe.get("artifact") if _v4_global(_v4_scope, 'isinstance')(universe, _v4_global(_v4_scope, 'dict')) else None
    if (
        not _v4_global(_v4_scope, 'isinstance')(universe, _v4_global(_v4_scope, 'dict'))
        or universe.get("status") != "READY"
        or not _v4_global(_v4_scope, 'isinstance')(universe.get("row_count"), _v4_global(_v4_scope, 'int'))
        or universe["row_count"] <= 0
        or not _v4_global(_v4_scope, 'isinstance')(artifact, _v4_global(_v4_scope, 'dict'))
    ):
        raise _v4_global(_v4_scope, 'RuntimeError')("STAGE_ACQUISITION_UNIVERSE_NOT_READY")
    unsafe_universe = [
        key
        for key in ("production_allowed", "buy_gate_updated", "orders_sent")
        if artifact.get(key) is not False
    ]
    if unsafe_universe:
        raise _v4_global(_v4_scope, 'RuntimeError')(
            "STAGE_ACQUISITION_UNIVERSE_UNSAFE:" + ",".join(unsafe_universe)
        )
    bundled_stage_root = (
        _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, '__file__')).resolve().parents[1] / "upstreams" / "v3_shared_data"
    )
    if not (bundled_stage_root / "scripts" / "run_scheduled_stage_bundle.py").is_file():
        raise _v4_global(_v4_scope, 'RuntimeError')(
            "BUNDLED_STAGE_ACQUISITION_MISSING:" + _v4_global(_v4_scope, 'str')(bundled_stage_root)
        )
    panel = _v4_global(_v4_scope, 'resolve_selector_panel')(selector_data_root, business_date)
    pointer = selector_data_root / "data_layer_interface_current" / "CURRENT_SELECTOR_READY_PANEL.txt"
    env = _v4_global(_v4_scope, 'build_proxy_environment')(_v4_global(_v4_scope, 'os').environ.copy())
    env.update(
        {
            "V3_SHARED_DATA_STORE_ROOT": _v4_global(_v4_scope, 'str')(shared_data_root),
            "V35_DATA_ROOT": _v4_global(_v4_scope, 'str')(data_root),
            "V3_SHARED_SELECTOR_READY_PANEL_POINTER": _v4_global(_v4_scope, 'str')(pointer),
            "V3_SHARED_SELECTOR_READY_PANEL": _v4_global(_v4_scope, 'str')(panel),
            "V3_SHARED_FUTU_PYTHON": _v4_global(_v4_scope, 'sys').executable,
            "NO_PROXY": "127.0.0.1,localhost,::1",
            "no_proxy": "127.0.0.1,localhost,::1",
        }
    )
    completed = process_runner(
        [
            _v4_global(_v4_scope, 'sys').executable,
            "-m",
            "scripts.run_scheduled_stage_bundle",
            "--trade-date",
            business_date,
            "--stage-id",
            stage_id,
        ],
        cwd=bundled_stage_root,
        env=env,
        timeout=timeout_seconds,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        shell=False,
    )
    payload = _v4_global(_v4_scope, '_last_json_object')(completed.stdout)
    if completed.returncode != 0 or not payload.get("ok") or payload.get("status") != "READY":
        detail = payload.get("error") or completed.stderr[-1200:] or payload.get("status")
        raise _v4_global(_v4_scope, 'RuntimeError')(f"SHARED_STAGE_ACQUISITION_FAILED:{stage_id}:{detail}")
    unsafe = [
        key
        for key in ("production_allowed", "buy_gate_updated", "orders_sent")
        if payload.get(key) is not False
    ]
    if unsafe:
        raise _v4_global(_v4_scope, 'RuntimeError')("SHARED_STAGE_ACQUISITION_UNSAFE:" + ",".join(unsafe))
    return {
        "status": "READY",
        "stage_id": stage_id,
        "receipt_path": payload.get("receipt_path"),
        "stage_acquisition_universe": {
            "status": universe["status"],
            "row_count": universe["row_count"],
            "run_id": universe.get("run_id"),
            "current_path": _v4_global(_v4_scope, 'str')(universe.get("current_path") or ""),
            "idempotent": _v4_global(_v4_scope, 'bool')(universe.get("idempotent")),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _ensure_stage_candidate_input_body(_v4_scope, /, *, data_root, business_date, universe_materializer):
    """Idempotently ensure the stage consumer has a verified candidate input.

    The shared Stage Center remains the sole raw/selection producer.  This
    small prerequisite is owned by the V3.5 scheduler so consume-only mode
    cannot leave a stage slot without the exact-date acquisition universe.
    """

    materializer = universe_materializer or _v4_global(_v4_scope, 'materialize_stage_acquisition_universe')
    universe = materializer(data_root, business_date)
    artifact = universe.get("artifact") if _v4_global(_v4_scope, 'isinstance')(universe, _v4_global(_v4_scope, 'dict')) else None
    if (
        not _v4_global(_v4_scope, 'isinstance')(universe, _v4_global(_v4_scope, 'dict'))
        or universe.get("status") != "READY"
        or not _v4_global(_v4_scope, 'isinstance')(universe.get("row_count"), _v4_global(_v4_scope, 'int'))
        or _v4_global(_v4_scope, 'isinstance')(universe.get("row_count"), _v4_global(_v4_scope, 'bool'))
        or universe["row_count"] <= 0
        or not _v4_global(_v4_scope, 'isinstance')(artifact, _v4_global(_v4_scope, 'dict'))
    ):
        raise _v4_global(_v4_scope, 'RuntimeError')("STAGE_ACQUISITION_UNIVERSE_NOT_READY")
    unsafe_universe = [
        key
        for key in ("production_allowed", "buy_gate_updated", "orders_sent")
        if artifact.get(key) is not False
    ]
    if unsafe_universe:
        raise _v4_global(_v4_scope, 'RuntimeError')(
            "STAGE_ACQUISITION_UNIVERSE_UNSAFE:" + ",".join(unsafe_universe)
        )
    return {
        "status": universe["status"],
        "row_count": universe["row_count"],
        "run_id": universe.get("run_id"),
        "current_path": _v4_global(_v4_scope, 'str')(
            _v4_global(_v4_scope, 'Path')(universe.get("current_path") or "").expanduser().resolve()
        ),
        "artifact_sha256": universe.get("artifact_sha256"),
        "manifest_sha256": universe.get("manifest_sha256"),
        "receipt_sha256": universe.get("receipt_sha256"),
        "idempotent": _v4_global(_v4_scope, 'bool')(universe.get("idempotent")),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _consume_shared_stage_selection_body(_v4_scope, /, *, business_date, slot, selection_root, stage_acquisition_universe):
    """Describe the shared selection consumed by this scheduler.

    An explicit ``V35_STAGE_CENTER_SELECTION_ROOT`` changes this boundary to
    read-only consumption.  In particular, this helper deliberately does not
    invoke the bundled raw/selection producer or publish an artifact.  The
    scheduler owns only the exact-date candidate-input prerequisite and
    reports its verified evidence alongside the consume-only envelope.
    """
    stage_id = _v4_global(_v4_scope, 'STAGE_BY_SLOT').get(slot)
    if stage_id is None:
        return {"status": "NOT_STAGE_SLOT", "write_performed": False}
    result = {
        "status": "CONSUME_ONLY",
        "stage_id": stage_id,
        "business_date": business_date,
        "selection_root": _v4_global(_v4_scope, 'str')(selection_root.expanduser().resolve()),
        "direct_acquisition_called": False,
        "producer_called": False,
        "write_performed": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if stage_acquisition_universe is not None:
        result["stage_acquisition_universe"] = _v4_global(_v4_scope, 'dict')(stage_acquisition_universe)
    selection = _v4_global(_v4_scope, 'StageSelectionConsumer')(selection_root).get(business_date, stage_id)
    result.update(
        {
            "selection_status": selection.get("status", "CANNOT_CONFIRM"),
            "selection_artifact_id": selection.get("artifact_id"),
            "selection_run_id": selection.get("run_id"),
            "selection_markets": selection.get("markets", {}),
            "cannot_confirm": _v4_global(_v4_scope, 'list')(selection.get("cannot_confirm") or []),
        }
    )
    return result
