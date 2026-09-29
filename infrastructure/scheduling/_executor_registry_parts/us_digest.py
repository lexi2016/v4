"""infrastructure.scheduling.executor_registry: us_digest (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _FixedExecutorRegistry__us_market_digest_body(_v4_scope, /, self, request):
    """Run only the seasonal US capture slot that is due now.

            Both DST variants are present in the catalog so launchd can remain a
            fixed-slot scheduler.  The explicit timezone resolver selects one
            active five-minute window; the other variant is a successful no-op and
            therefore cannot overwrite a same-session phase.
            """
    from ops.us_market_digest import resolve_capture_for_shanghai_slot, us_market_day_certification
    from infrastructure.data_store import _sha256

    module = "ops.us_market_digest"
    try:
        capture = resolve_capture_for_shanghai_slot(
            request.business_date,
            request.slot,
        )
    except _v4_global(_v4_scope, 'ValueError') as error:
        if _v4_global(_v4_scope, 'str')(error) == "US_CAPTURE_SLOT_NOT_DUE":
            return {
                "status": "SUCCEEDED",
                "modules": [module],
                "exit_code": 0,
                "capture_status": "NOT_DUE",
                "capture_performed": False,
                "capture_artifact_verified": False,
                "data_update_status": "NOT_DUE_NO_UPDATE",
                "collector_invoked": False,
                "new_capture_verified": False,
                "capture_slot": request.slot,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        failure = self._failure_result(
            "us_market_digest",
            [module],
            _v4_global(_v4_scope, 'str')(error),
        )
        failure["failure_class"] = "INVALID_INPUT"
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(failure) from error

    market_day = us_market_day_certification(capture["us_session_date"])
    if market_day["status"] == "CLOSED":
        return {
            "status": "SUCCEEDED",
            "modules": [module],
            "exit_code": 0,
            "capture_status": "CLOSED",
            "capture_performed": False,
            "capture_artifact_verified": False,
            "data_update_status": "OFFICIAL_MARKET_CLOSED_NO_UPDATE",
            "collector_invoked": False,
            "new_capture_verified": False,
            "capture_phase": capture["capture_phase"],
            "us_session_date": capture["us_session_date"],
            "market_day_status": market_day["status"],
            "market_day_reason": market_day["reason"],
            "market_day_close_at": market_day.get("close_at"),
            "market_calendar_source_url": market_day.get("source_url"),
            "cannot_confirm": [],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    if market_day["status"] != "VERIFIED":
        failure = self._failure_result(
            "us_market_digest", [module], "US_MARKET_CALENDAR_UNVERIFIED"
        )
        failure["failure_class"] = "CONTRACT"
        failure["market_day_status"] = market_day.get("status")
        failure["market_day_reason"] = market_day.get("reason")
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(failure)

    session = capture["us_session_date"]
    store = _v4_global(_v4_scope, 'ResearchPeripheralStore')(self.data_root)
    try:
        before = store.read_exact(session, "external_finance")
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'AttributeError')) as error:
        failure = self._failure_result(
            "us_market_digest", [module], "US_CAPTURE_PREIMAGE_INVALID"
        )
        failure.update(failure_class="CONTRACT", detail=_v4_global(_v4_scope, 'str')(error))
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(failure) from error
    before_sha = _sha256(before) if before is not None else None
    before_receipt_sha = (
        _sha256(store._receipt(before, before_sha))
        if before is not None and before_sha is not None
        else None
    )

    result = self._run(
        module,
        [
            "--data-root", _v4_global(_v4_scope, 'str')(self.data_root),
            "--trade-date", capture["us_session_date"],
            "--capture-phase", capture["capture_phase"],
            "--timeout", _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, '_PERIPHERAL_FETCH_TIMEOUT_SECONDS')),
        ],
    )
    result["modules"] = [module]
    result["capture_phase"] = capture["capture_phase"]
    result["us_session_date"] = capture["us_session_date"]
    result["market_day_status"] = market_day["status"]
    result["market_day_reason"] = market_day["reason"]
    result["market_day_close_at"] = market_day.get("close_at")
    result["market_calendar_source_url"] = market_day.get("source_url")
    result["cannot_confirm"] = []
    if result["status"] != "SUCCEEDED":
        result["failure_class"] = "EXTERNAL_SOURCE"
        result["reason"] = "US_MARKET_CAPTURE_FAILED"
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(result)
    try:
        payload = _v4_global(_v4_scope, 'json').loads(_v4_global(_v4_scope, 'str')(result.get("stdout") or "{}"))
    except _v4_global(_v4_scope, 'json').JSONDecodeError as error:
        result.update(
            {
                "status": "FAILED",
                "failure_class": "CONTRACT",
                "reason": "US_MARKET_CAPTURE_INVALID_RESULT",
            }
        )
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(result) from error
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'dict')) or payload.get("status") not in {
        "READY",
        "READY_EMPTY",
    }:
        result.update(
            {
                "status": "FAILED",
                "failure_class": "UPSTREAM_NOT_READY",
                "reason": "US_MARKET_CAPTURE_NOT_READY",
                "capture_status": payload.get("status") if _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'dict')) else None,
            }
        )
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(result)
    try:
        stored = store.read_exact(session, "external_finance")
        expected_path = store._relative(session, "external_finance")
        expected_receipt_path = store._receipt_relative(session, "external_finance")
        snapshot = (stored or {}).get("market_snapshot") or {}
        captures = (stored or {}).get("us_session_captures") or []
        session_phase_capture_exists = _v4_global(_v4_scope, 'any')(
            _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'dict'))
            and row.get("us_session_date") == session
            and row.get("capture_phase") == capture["capture_phase"]
            and row.get("original_time_capture") is True
            for row in captures
        )
        provenance_fields = (
            "reused",
            "replaced",
            "receipt_path",
            "capture_us_session_date",
            "capture_phase",
            "capture_id",
            "capture_run_id",
            "capture_captured_at",
            "capture_capture_origin",
            "capture_original_time",
        )
        provenance_complete = _v4_global(_v4_scope, 'all')(field in payload for field in provenance_fields)
        if provenance_complete and (
            _v4_global(_v4_scope, 'type')(payload.get("reused")) is not _v4_global(_v4_scope, 'bool')
            or _v4_global(_v4_scope, 'type')(payload.get("replaced")) is not _v4_global(_v4_scope, 'bool')
        ):
            raise _v4_global(_v4_scope, 'ValueError')("US CLI provenance flags must be boolean")
        capture_rows = [
            row
            for row in captures
            if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'dict'))
            and row.get("us_session_date") == session
            and row.get("capture_phase") == capture["capture_phase"]
            and row.get("capture_id") == payload.get("capture_id")
            and row.get("run_id") == payload.get("capture_run_id")
        ]
        exact_capture = capture_rows[0] if _v4_global(_v4_scope, 'len')(capture_rows) == 1 else {}
        if (stored is None or payload.get("trade_date") != session
                or payload.get("source") != "external_finance"
                or payload.get("payload_path") != expected_path
                or (payload.get("receipt_path") is not None
                    and payload.get("receipt_path") != expected_receipt_path)
                or payload.get("payload_sha256") != _sha256(stored)
                or stored.get("status") != payload["status"]
                or not session_phase_capture_exists
                or snapshot.get("capture_session_date") != session
                or (capture["capture_phase"] == "POST_CLOSE" and snapshot.get("status") != "READY")):
            raise _v4_global(_v4_scope, 'ValueError')("US exact artifact/manifest/receipt capture identity mismatch")
        after_sha = _sha256(stored)
        after_receipt_sha = _sha256(store._receipt(stored, after_sha))
        new_capture_verified = False
        if provenance_complete:
            if (
                payload.get("receipt_path") != expected_receipt_path
                or payload.get("capture_us_session_date") != session
                or payload.get("capture_phase") != capture["capture_phase"]
                or not exact_capture
                or not _v4_global(_v4_scope, 'isinstance')(payload.get("capture_id"), _v4_global(_v4_scope, 'str'))
                or not payload.get("capture_id")
                or not _v4_global(_v4_scope, 'isinstance')(payload.get("capture_run_id"), _v4_global(_v4_scope, 'str'))
                or not payload.get("capture_run_id")
                or not _v4_global(_v4_scope, 'isinstance')(payload.get("capture_captured_at"), _v4_global(_v4_scope, 'str'))
                or not payload.get("capture_captured_at")
                or payload.get("capture_capture_origin") != "ORIGINAL_TIME_CAPTURE"
                or payload.get("capture_original_time") is not True
                or exact_capture.get("captured_at") != payload.get("capture_captured_at")
                or exact_capture.get("capture_origin") != payload.get("capture_capture_origin")
                or exact_capture.get("original_time_capture") is not True
            ):
                raise _v4_global(_v4_scope, 'ValueError')("US CLI capture identity differs from the stored receipt")
            before_captures = (before or {}).get("us_session_captures") or []
            capture_was_preexisting = _v4_global(_v4_scope, 'any')(
                _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'dict'))
                and row.get("us_session_date") == session
                and row.get("capture_phase") == capture["capture_phase"]
                and row.get("capture_id") == exact_capture.get("capture_id")
                and row.get("run_id") == exact_capture.get("run_id")
                and row.get("captured_at") == exact_capture.get("captured_at")
                for row in before_captures
            )
            reused = payload["reused"]
            replaced = payload["replaced"]
            if reused:
                if (
                replaced
                or before is None
                or before_sha != after_sha
                or before_receipt_sha != after_receipt_sha
                or not capture_was_preexisting
                ):
                    raise _v4_global(_v4_scope, 'ValueError')("US reused capture does not match the exact before/after artifact")
            elif before is None:
                if replaced:
                    raise _v4_global(_v4_scope, 'ValueError')("US initial publication cannot be a replacement")
                new_capture_verified = after_sha != before_sha and not capture_was_preexisting
            elif replaced:
                if before_sha == after_sha or before_receipt_sha == after_receipt_sha:
                    raise _v4_global(_v4_scope, 'ValueError')("US replacement did not change the exact artifact")
                new_capture_verified = not capture_was_preexisting
            elif before_sha != after_sha or before_receipt_sha != after_receipt_sha:
                raise _v4_global(_v4_scope, 'ValueError')("US artifact changed without replacement provenance")
        result["receipt_verified"] = True
        result["receipt_path"] = expected_receipt_path
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'AttributeError')) as error:
        result.update(status="FAILED", failure_class="CONTRACT", reason="US_CAPTURE_EVIDENCE_INVALID")
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(result) from error
    result.update(
        {
            "capture_status": payload["status"],
            "collector_invoked": True,
            "capture_artifact_verified": True,
            "new_capture_verified": new_capture_verified,
            "capture_reused": payload.get("reused") if provenance_complete else None,
            "capture_replaced": payload.get("replaced") if provenance_complete else None,
            "capture_before_payload_sha256": before_sha,
            "capture_after_payload_sha256": after_sha,
            "capture_before_receipt_sha256": before_receipt_sha,
            "capture_after_receipt_sha256": after_receipt_sha,
            "capture_id": payload.get("capture_id") if provenance_complete else None,
            "capture_run_id": payload.get("capture_run_id") if provenance_complete else None,
            "capture_captured_at": payload.get("capture_captured_at") if provenance_complete else None,
            "capture_performed": new_capture_verified if provenance_complete else None,
            "data_update_status": (
                "EXACT_NEW_CAPTURE_VERIFIED"
                if new_capture_verified
                else (
                    "EXACT_ARTIFACT_REUSED"
                    if provenance_complete and payload["reused"]
                    else "EXACT_ARTIFACT_VERIFIED_UPDATE_UNCONFIRMED"
                )
            ),
            "payload_path": payload.get("payload_path"),
            "payload_sha256": payload.get("payload_sha256"),
            "capture_origin": payload.get("capture_origin"),
            "original_time_capture": payload.get("original_time_capture"),
        }
    )
    return result
