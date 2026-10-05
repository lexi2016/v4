"""ops.macos_research_panel_daily: scheduled_readiness (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __fast_path_lane_detail_body(_v4_scope, /, receipt_root, lane, target_date, *, ready):
    """Project an already verified dated receipt into the public lane envelope.

    The after-1700 fast path must remain idempotent without turning an old or
    malformed ``READY`` file into a new readiness claim.  The lane validators
    establish ``ready``; this helper rereads the same exact-date bytes only to
    carry their digest/size and a truthful lane status to the registry.
    """

    target = _v4_global(_v4_scope, '_date')(target_date)
    name = f"{lane.lower()}-{target}.json"
    try:
        raw = _v4_global(_v4_scope, 'SafeRoot')(receipt_root).read_bytes(name)
        receipt = _v4_global(_v4_scope, 'json').loads(raw.decode("utf-8-sig"))
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError, _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
        return {
            "status": "CANNOT_CONFIRM",
            "lane_ready": False,
            "runner_called": False,
            "receipt_written": False,
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
    identity_ok = (
        _v4_global(_v4_scope, 'isinstance')(receipt, _v4_global(_v4_scope, 'Mapping'))
        and receipt.get("schema_version") == "v3.macos.research_panel_receipt.v1"
        and receipt.get("lane") == lane
        and _v4_global(_v4_scope, 'str')(receipt.get("target_date") or "") == target
        and _v4_global(_v4_scope, '_receipt_safety_is_false')(receipt)
    )
    status = _v4_global(_v4_scope, 'str')(receipt.get("status") or "CANNOT_CONFIRM").upper() if identity_ok else "CANNOT_CONFIRM"
    lane_ready = _v4_global(_v4_scope, 'bool')(ready and status == "READY")
    if status == "READY" and not lane_ready:
        status = "CANNOT_CONFIRM"
    return {
        "status": status,
        "lane_ready": lane_ready,
        "runner_called": False,
        "receipt_written": True,
        "receipt_sha256": _v4_global(_v4_scope, 'hashlib').sha256(raw).hexdigest(),
        "receipt_bytes": _v4_global(_v4_scope, 'len')(raw),
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }


def __a_lane_receipt_ready_body(_v4_scope, /, receipt_root, target_date, selector_ready, payload, formula_generation_pointer):
    """Require exact A selector plus the formula's exact backtest readiness."""

    if not selector_ready:
        return False, False
    receipt = payload or _v4_global(_v4_scope, '_read_lane_receipt')(receipt_root, "A", target_date)
    if not _v4_global(_v4_scope, 'isinstance')(receipt, _v4_global(_v4_scope, 'Mapping')):
        return False, False
    if (
        receipt.get("status") != "READY"
        or _v4_global(_v4_scope, 'str')(receipt.get("target_date") or "") != _v4_global(_v4_scope, '_date')(target_date)
        or not _v4_global(_v4_scope, '_receipt_safety_is_false')(receipt)
    ):
        return False, False
    generation_verified = False
    if formula_generation_pointer is not None:
        try:
            generation = _v4_global(_v4_scope, 'read_formula_generation')(
                formula_generation_pointer,
                expected_target_date=_v4_global(_v4_scope, '_date')(target_date),
                require_source=True,
            )
            receipt_generation = receipt.get("generation")
            if not _v4_global(_v4_scope, 'isinstance')(receipt_generation, _v4_global(_v4_scope, 'Mapping')):
                formula = receipt.get("formula")
                receipt_generation = formula.get("generation_pointer") if _v4_global(_v4_scope, 'isinstance')(formula, _v4_global(_v4_scope, 'Mapping')) else None
            if not _v4_global(_v4_scope, 'isinstance')(receipt_generation, _v4_global(_v4_scope, 'Mapping')):
                return False, False
            if (
                _v4_global(_v4_scope, 'str')(receipt_generation.get("generation_id") or "") != generation["generation_id"]
                or _v4_global(_v4_scope, 'str')(receipt_generation.get("sha256") or "").lower() != generation["sha256"]
                or _v4_global(_v4_scope, 'str')(receipt_generation.get("path") or "") != _v4_global(_v4_scope, 'str')(generation["path"])
            ):
                return False, False
            generation_verified = True
        except (_v4_global(_v4_scope, 'FormulaGenerationError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'ValueError')):
            return False, False
    backtest_ready = receipt.get("backtest_pointer_ready")
    formula = receipt.get("formula")
    if backtest_ready is None and _v4_global(_v4_scope, 'isinstance')(formula, _v4_global(_v4_scope, 'Mapping')):
        backtest_ready = formula.get("backtest_pointer_ready")
    # The strict generation pointer is the authoritative pair.  Its reader
    # has already verified the exact backtest artifact and target date, so a
    # legacy receipt that predates ``backtest_pointer_ready`` remains usable
    # only when that strict pair was verified above.
    if backtest_ready is None and generation_verified:
        backtest_ready = True
    return backtest_ready is True, backtest_ready is True


def __hk_lane_receipt_ready_body(_v4_scope, /, receipt_root, target_date, payload):
    """Require the exact HK date receipt and a non-empty verified snapshot."""

    receipt = payload or _v4_global(_v4_scope, '_read_lane_receipt')(receipt_root, "HK", target_date)
    if not _v4_global(_v4_scope, 'isinstance')(receipt, _v4_global(_v4_scope, 'Mapping')):
        return False
    try:
        row_count = _v4_global(_v4_scope, 'int')(receipt.get("row_count") or 0)
        coverage_rate = _v4_global(_v4_scope, 'float')(receipt.get("coverage_rate") or 0.0)
    except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
        return False
    digest = receipt.get("sha256")
    return _v4_global(_v4_scope, 'bool')(
        receipt.get("status") == "READY"
        and _v4_global(_v4_scope, 'str')(receipt.get("target_date") or "") == _v4_global(_v4_scope, '_date')(target_date)
        and _v4_global(_v4_scope, '_receipt_safety_is_false')(receipt)
        and _v4_global(_v4_scope, 'isinstance')(digest, _v4_global(_v4_scope, 'str'))
        and _v4_global(_v4_scope, 'bool')(digest.strip())
        and row_count > 0
        and coverage_rate > 0.0
    )


def _ensure_after_1700_body(_v4_scope, /, *, target_date, receipt_root, selector_pointer, a_runner, hk_runner, lane, now, formula_generation_pointer):
    """Idempotently ensure the daily panel after 17:00.

    StartInterval can invoke this function repeatedly.  Explicit lane callers
    use only their exact dated receipt as a fast path: A requires selector and
    backtest readiness, HK requires a verified HK snapshot, and ALL requires
    both.  The dated attempt marker applies only a bounded time backoff and
    never converts a stale pointer into a permanent success or permanent
    lockout.
    """

    target = _v4_global(_v4_scope, '_date')(target_date)
    requested_lane = _v4_global(_v4_scope, '_normalize_lane')(lane or "ALL")
    strict_lane_readiness = lane is not None
    moment = now or _v4_global(_v4_scope, '_datetime').datetime.now(_v4_global(_v4_scope, 'ZoneInfo')("Asia/Shanghai"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_v4_global(_v4_scope, 'ZoneInfo')("Asia/Shanghai"))
    else:
        moment = moment.astimezone(_v4_global(_v4_scope, 'ZoneInfo')("Asia/Shanghai"))
    common = {
        "schema_version": "v3.macos.research_panel_after_1700_ensure.v1",
        "target_date": target,
        "observed_at": moment.isoformat(),
        "selector_pointer": _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(selector_pointer).expanduser().resolve()) if selector_pointer is not None else None,
        "formula_generation_pointer": _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(formula_generation_pointer).expanduser().resolve()) if formula_generation_pointer is not None else None,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if moment.hour < 17:
        return {**common, "status": "BEFORE_1700", "runner_called": False, "idempotent": True}
    selector_ready = (
        _v4_global(_v4_scope, 'selector_pointer_is_ready')(selector_pointer, target, formula_generation_pointer)
        if requested_lane != "HK"
        else False
    ) if formula_generation_pointer is not None else (
        _v4_global(_v4_scope, 'selector_pointer_is_ready')(selector_pointer, target) if requested_lane != "HK" else False
    )
    common["selector_pointer_ready"] = selector_ready
    a_ready, backtest_ready = _v4_global(_v4_scope, '_a_lane_receipt_ready')(
        receipt_root,
        target,
        selector_ready,
        formula_generation_pointer=formula_generation_pointer,
    ) if formula_generation_pointer is not None else _v4_global(_v4_scope, '_a_lane_receipt_ready')(
        receipt_root, target, selector_ready
    )
    hk_ready = _v4_global(_v4_scope, '_hk_lane_receipt_ready')(receipt_root, target)
    common.update(
        {
            "a_lane_ready": a_ready,
            "hk_lane_ready": hk_ready,
            "backtest_pointer_ready": backtest_ready,
        }
    )
    already_ready = (
        (requested_lane == "A" and a_ready)
        or (requested_lane == "HK" and hk_ready)
        or (requested_lane == "ALL" and a_ready and hk_ready)
    )
    # Calls that predate the explicit lane contract retain the old selector
    # fast path; launchd and all current callers pass lane explicitly.
    if already_ready or (selector_ready and not strict_lane_readiness and requested_lane == "ALL"):
        requested = {"A", "HK"} if requested_lane == "ALL" else {requested_lane}
        lanes = {
            name: (
                _v4_global(_v4_scope, '_fast_path_lane_detail')(receipt_root, name, target, ready=ready)
                if name in requested
                else _v4_global(_v4_scope, '_not_requested_lane')()
            )
            for name, ready in (("A", a_ready), ("HK", hk_ready))
        }
        fast_path_verified = _v4_global(_v4_scope, 'all')(lanes[name].get("lane_ready") is True for name in requested)
        if not already_ready or fast_path_verified:
            return {
                **common,
                "status": "ALREADY_READY",
                "runner_called": False,
                "idempotent": True,
                "lanes": lanes,
                **({"lane_ready": already_ready, "requested_lane": requested_lane} if strict_lane_readiness else {}),
            }

    attempt_path = _v4_global(_v4_scope, '_after_1700_attempt_path')(receipt_root, target)
    if requested_lane != "ALL":
        # Lane-local backoff; a failed A update must not suppress HK work.
        attempt_path = attempt_path.with_name(f"{target}-{requested_lane.lower()}.json")
    if attempt_path.is_file():
        try:
            payload = _v4_global(_v4_scope, 'json').loads(attempt_path.read_text(encoding="utf-8-sig"))
        except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError):
            payload = {}
        if _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
            attempt_count = _v4_global(_v4_scope, 'int')(payload.get("attempt_count") or 1)
            previous_raw = _v4_global(_v4_scope, 'str')(payload.get("observed_at") or "")
            try:
                previous = _v4_global(_v4_scope, '_datetime').datetime.fromisoformat(previous_raw)
                if previous.tzinfo is None:
                    previous = previous.replace(tzinfo=_v4_global(_v4_scope, 'ZoneInfo')("Asia/Shanghai"))
                elapsed = (moment - previous.astimezone(_v4_global(_v4_scope, 'ZoneInfo')("Asia/Shanghai"))).total_seconds()
            except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'OverflowError')):
                elapsed = 300.0
            if elapsed < 300.0:
                return {
                    **common,
                    **_v4_global(_v4_scope, 'dict')(payload),
                    "status": "RETRY_BACKOFF",
                    "runner_called": False,
                    "idempotent": True,
                }
        else:
            attempt_count = 1
    else:
        attempt_count = 0

    result = _v4_global(_v4_scope, 'run_lanes')(
        target_date=target,
        receipt_root=receipt_root,
        a_runner=a_runner,
        hk_runner=hk_runner,
        lane=requested_lane,
    )
    selector_ready_after = (
        _v4_global(_v4_scope, 'selector_pointer_is_ready')(selector_pointer, target, formula_generation_pointer)
        if requested_lane != "HK"
        else False
    ) if formula_generation_pointer is not None else (
        _v4_global(_v4_scope, 'selector_pointer_is_ready')(selector_pointer, target) if requested_lane != "HK" else False
    )
    a_payload = (result.get("lanes") or {}).get("A") if _v4_global(_v4_scope, 'isinstance')(result.get("lanes"), _v4_global(_v4_scope, 'Mapping')) else None
    hk_payload = (result.get("lanes") or {}).get("HK") if _v4_global(_v4_scope, 'isinstance')(result.get("lanes"), _v4_global(_v4_scope, 'Mapping')) else None
    a_ready_after, backtest_ready_after = (
        _v4_global(_v4_scope, '_a_lane_receipt_ready')(
            receipt_root,
            target,
            selector_ready_after,
            a_payload if _v4_global(_v4_scope, 'isinstance')(a_payload, _v4_global(_v4_scope, 'Mapping')) else None,
            formula_generation_pointer,
        )
        if formula_generation_pointer is not None
        else _v4_global(_v4_scope, '_a_lane_receipt_ready')(
            receipt_root, target, selector_ready_after, a_payload if _v4_global(_v4_scope, 'isinstance')(a_payload, _v4_global(_v4_scope, 'Mapping')) else None
        )
    )
    hk_ready_after = _v4_global(_v4_scope, '_hk_lane_receipt_ready')(
        receipt_root, target, hk_payload if _v4_global(_v4_scope, 'isinstance')(hk_payload, _v4_global(_v4_scope, 'Mapping')) else None
    )
    lane_ready = (
        (requested_lane == "A" and a_ready_after)
        or (requested_lane == "HK" and hk_ready_after)
        or (requested_lane == "ALL" and a_ready_after and hk_ready_after)
    )
    payload = {
        **common,
        "status": "ATTEMPTED",
        "runner_called": True,
        "idempotent": False,
        "attempt_count": attempt_count + 1,
        "overall_status": result.get("overall_status"),
        "requested_lane": requested_lane,
        "lanes": result.get("lanes", {}),
        "selector_pointer_ready": selector_ready_after,
        "a_lane_ready": a_ready_after,
        "hk_lane_ready": hk_ready_after,
        "backtest_pointer_ready": backtest_ready_after,
        "lane_ready": lane_ready,
    }
    attempt_path.parent.mkdir(parents=True, exist_ok=True)
    _v4_global(_v4_scope, '_atomic_write')(attempt_path, (_v4_global(_v4_scope, 'json').dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    return payload


def _ensure_exit_code_body(_v4_scope, /, result):
    """Map an after-17:00 result to a truthful process exit code.

    A retry marker or a completed attempt is not success evidence while the
    selector pointer still misses the exact target date.  launchd must keep
    retrying those results instead of recording a false healthy run.
    """

    status = _v4_global(_v4_scope, 'str')(result.get("status") or "")
    if "lane_ready" in result:
        lane_ready = result.get("lane_ready") is True
        if status == "BEFORE_1700":
            return 0
        if status in {"ALREADY_READY", "ATTEMPTED"} and lane_ready:
            return 0
        return 2
    pointer_ready = result.get("selector_pointer_ready") is True
    backtest_pointer = result.get("backtest_pointer_ready")
    if backtest_pointer is None:
        lanes = result.get("lanes")
        if _v4_global(_v4_scope, 'isinstance')(lanes, _v4_global(_v4_scope, 'Mapping')):
            a_lane = lanes.get("A") or lanes.get("a")
            if _v4_global(_v4_scope, 'isinstance')(a_lane, _v4_global(_v4_scope, 'Mapping')):
                formula = a_lane.get("formula")
                if _v4_global(_v4_scope, 'isinstance')(formula, _v4_global(_v4_scope, 'Mapping')):
                    backtest_pointer = formula.get("backtest_pointer_ready")
    if backtest_pointer is False:
        pointer_ready = False
    if status == "BEFORE_1700":
        return 0
    if status == "ALREADY_READY" and pointer_ready:
        return 0
    if status == "ATTEMPTED" and pointer_ready:
        return 0
    return 2
