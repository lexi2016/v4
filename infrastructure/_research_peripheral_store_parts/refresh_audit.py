"""infrastructure.research_peripheral_store: refresh_audit (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _ResearchPeripheralStore_record_refresh_attempt_body(_v4_scope, /, self, attempted_payload, *, retained_payload, reason):
    """Record a failed refresh without replacing a verified READY value."""
    trade_date, source = _v4_global(_v4_scope, 'validate_research_peripheral')(attempted_payload)
    retained_date, retained_source = _v4_global(_v4_scope, 'validate_research_peripheral')(
        retained_payload,
        expected_trade_date=trade_date,
        expected_source=source,
    )
    if (retained_date, retained_source) != (trade_date, source):
        raise _v4_global(_v4_scope, 'ValueError')("research peripheral retained identity mismatch")
    if attempted_payload.get("status") != "CANNOT_CONFIRM":
        raise _v4_global(_v4_scope, 'ValueError')("refresh attempt must be CANNOT_CONFIRM")
    if retained_payload.get("status") not in {"READY", "READY_EMPTY"}:
        raise _v4_global(_v4_scope, 'ValueError')("refresh attempt requires a retained READY payload")
    normalized_reason = _v4_global(_v4_scope, 'str')(reason or "").strip()
    if not normalized_reason:
        raise _v4_global(_v4_scope, 'ValueError')("refresh attempt reason is required")
    attempted_sha = _v4_global(_v4_scope, '_sha256')(attempted_payload)
    retained_sha = _v4_global(_v4_scope, '_sha256')(retained_payload)
    relative = (
        f"receipts/research/peripherals/refresh_attempts/{trade_date}/"
        f"{source}/{attempted_sha}.json"
    )
    record = {
        "schema_version": "v3_5.research_peripheral_refresh_attempt.v1",
        "trade_date": trade_date,
        "source": source,
        "attempted_status": "CANNOT_CONFIRM",
        "attempted_item_count": _v4_global(_v4_scope, 'int')(attempted_payload["item_count"]),
        "attempted_fetched_at": attempted_payload["fetched_at"],
        "attempted_cannot_confirm": _v4_global(_v4_scope, 'list')(attempted_payload["cannot_confirm"]),
        "attempted_payload_sha256": attempted_sha,
        "retained_status": retained_payload["status"],
        "retained_item_count": _v4_global(_v4_scope, 'int')(retained_payload["item_count"]),
        "retained_fetched_at": retained_payload["fetched_at"],
        "retained_payload_sha256": retained_sha,
        "reason": normalized_reason,
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    attempted_snapshot = attempted_payload.get("market_snapshot")
    if _v4_global(_v4_scope, 'isinstance')(attempted_snapshot, _v4_global(_v4_scope, 'Mapping')):
        record["attempted_market_snapshot_status"] = _v4_global(_v4_scope, 'str')(
            attempted_payload.get("market_snapshot_status")
            or attempted_snapshot.get("status")
            or "CANNOT_CONFIRM"
        )
        record["attempted_market_snapshot_cannot_confirm"] = _v4_global(_v4_scope, 'list')(
            attempted_snapshot.get("cannot_confirm") or []
        )
    attempted_captures = attempted_payload.get("us_session_captures")
    if _v4_global(_v4_scope, 'isinstance')(attempted_captures, _v4_global(_v4_scope, 'list')):
        attempted_capture = _v4_global(_v4_scope, 'next')(
            (
                row
                for row in attempted_captures
                if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))
                and row.get("capture_phase") == "POST_CLOSE"
            ),
            None,
        )
        if _v4_global(_v4_scope, 'isinstance')(attempted_capture, _v4_global(_v4_scope, 'Mapping')):
            # Preserve the failed capture identity alongside its digest;
            # the canonical artifact remains the verified last-known
            # payload and is intentionally not overwritten by this attempt.
            for field, receipt_field in (
                ("capture_id", "attempted_capture_id"),
                ("capture_phase", "attempted_capture_phase"),
                ("us_session_date", "attempted_capture_session_date"),
                ("run_id", "attempted_run_id"),
                ("captured_at", "attempted_captured_at"),
                ("capture_mode", "attempted_capture_mode"),
                ("reason", "attempted_capture_reason"),
                ("capture_reason", "attempted_capture_reason_detail"),
                ("late", "attempted_late"),
                (
                    "natural_capture_window_start",
                    "attempted_natural_capture_window_start",
                ),
                (
                    "natural_capture_window_end",
                    "attempted_natural_capture_window_end",
                ),
                (
                    "allowed_recovery_window_start",
                    "attempted_allowed_recovery_window_start",
                ),
                (
                    "allowed_recovery_window_end",
                    "attempted_allowed_recovery_window_end",
                ),
            ):
                if attempted_capture.get(field) is not None:
                    record[receipt_field] = (
                        _v4_global(_v4_scope, 'bool')(attempted_capture[field])
                        if field == "late"
                        else _v4_global(_v4_scope, 'str')(attempted_capture[field])
                    )
    with self._lock():
        path = self._path(relative)
        if path.exists():
            if not path.is_file() or self._read(relative) != record:
                raise _v4_global(_v4_scope, 'ValueError')("research peripheral refresh attempt conflict")
        else:
            self._write(relative, record)
    return {
        "refresh_attempt_path": relative,
        "attempted_payload_sha256": attempted_sha,
        "retained_payload_sha256": retained_sha,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
