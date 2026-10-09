"""infrastructure.research_peripheral_store: publish_read (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _ResearchPeripheralStore__receipt_body(_v4_scope, /, cls, payload, digest):
    trade_date = _v4_global(_v4_scope, 'str')(payload["trade_date"])
    source = _v4_global(_v4_scope, 'str')(payload["source"])
    receipt = {
        "schema_version": _v4_global(_v4_scope, '_RECEIPT_SCHEMA_VERSION'),
        "trade_date": trade_date,
        "source": source,
        "payload_path": cls._relative(trade_date, source),
        "payload_sha256": digest,
        "item_count": _v4_global(_v4_scope, 'int')(payload["item_count"]),
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if "feed_receipts" in payload:
        receipt["feed_receipts"] = [_v4_global(_v4_scope, 'dict')(item) for item in payload["feed_receipts"]]
    if "market_snapshot" in payload:
        receipt["market_snapshot_sha256"] = _v4_global(_v4_scope, '_sha256')(payload["market_snapshot"])
        receipt["market_snapshot_schema_version"] = _v4_global(_v4_scope, 'str')(
            payload["market_snapshot"].get("schema_version") or ""
        )
        receipt["market_snapshot_captured_at"] = _v4_global(_v4_scope, 'str')(
            payload["market_snapshot"].get("captured_at") or ""
        )
        receipt["market_snapshot_source_response_sha256"] = _v4_global(_v4_scope, 'str')(
            payload["market_snapshot"].get("source_response_sha256") or ""
        )
        receipt["market_snapshot_status"] = _v4_global(_v4_scope, 'str')(
            payload["market_snapshot"].get("status") or "CANNOT_CONFIRM"
        )
        receipt["market_snapshot_status"] = _v4_global(_v4_scope, 'str')(
            payload.get("market_snapshot_status")
            or receipt["market_snapshot_status"]
        )
    captures = payload.get("us_session_captures")
    if _v4_global(_v4_scope, 'isinstance')(captures, _v4_global(_v4_scope, 'list')):
        late_capture = _v4_global(_v4_scope, 'next')(
            (
                row
                for row in _v4_global(_v4_scope, 'reversed')(captures)
                if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')) and row.get("late") is True
            ),
            None,
        )
        if _v4_global(_v4_scope, 'isinstance')(late_capture, _v4_global(_v4_scope, 'Mapping')):
            for field in (
                "capture_id",
                "run_id",
                "us_session_date",
                "capture_phase",
                "captured_at",
                "capture_origin",
                "original_time_capture",
                "rss_status",
                "rss_item_count",
                "rss_raw_item_count",
                "quote_capture_status",
                "quote_capture_reason",
                "capture_mode",
                "reason",
                "capture_reason",
                "late",
                "natural_capture_window_start",
                "natural_capture_window_end",
                "allowed_recovery_window_start",
                "allowed_recovery_window_end",
            ):
                if field in late_capture:
                    receipt[field] = late_capture[field]
    return receipt


def _ResearchPeripheralStore_receipt_matches_body(_v4_scope, /, cls, payload, digest, stored_receipt):
    """Allow only the exact old receipt with both derivable fields absent."""
    expected = cls._receipt(payload, digest)
    if stored_receipt == expected:
        return True
    if not _v4_global(_v4_scope, 'isinstance')(stored_receipt, _v4_global(_v4_scope, 'Mapping')):
        return False
    legacy_fields = _v4_global(_v4_scope, '_LEGACY_MARKET_SNAPSHOT_RECEIPT_FIELDS')
    if not legacy_fields.issubset(expected):
        return False
    captured_at = expected.get("market_snapshot_captured_at")
    source_sha256 = expected.get("market_snapshot_source_response_sha256")
    if (
        not _v4_global(_v4_scope, 'isinstance')(captured_at, _v4_global(_v4_scope, 'str'))
        or not captured_at
        or not _v4_global(_v4_scope, '_SHA256').fullmatch(_v4_global(_v4_scope, 'str')(source_sha256 or ""))
    ):
        return False
    legacy_shape = {key: value for key, value in expected.items() if key not in legacy_fields}
    return _v4_global(_v4_scope, 'dict')(stored_receipt) == legacy_shape


def _ResearchPeripheralStore_publish_body(_v4_scope, /, self, payload):
    trade_date, source = _v4_global(_v4_scope, 'validate_research_peripheral')(payload)
    relative = self._relative(trade_date, source)
    receipt_relative = self._receipt_relative(trade_date, source)
    digest = _v4_global(_v4_scope, '_sha256')(payload)
    receipt = self._receipt(payload, digest)
    artifact_path = self._path(relative)
    receipt_path = self._path(receipt_relative)
    with self._lock():
        manifest = self._manifest()
        existing = manifest.get(relative)
        if existing and existing != digest:
            raise _v4_global(_v4_scope, 'ValueError')("conflicting research peripheral re-import")
        if existing:
            if (
                not artifact_path.is_file()
                or _v4_global(_v4_scope, '_sha256')(self._read(relative)) != digest
                or not receipt_path.is_file()
                or not self._receipt_matches(payload, digest, self._read(receipt_relative))
            ):
                raise _v4_global(_v4_scope, 'ValueError')("research peripheral integrity mismatch")
        else:
            if artifact_path.exists() or receipt_path.exists():
                raise _v4_global(_v4_scope, 'ValueError')("orphan research peripheral artifact or receipt")
            self._write(relative, payload)
            self._write(receipt_relative, receipt)
            manifest[relative] = digest
            self._write_manifest(manifest)
    return {
        "trade_date": trade_date,
        "source": source,
        "payload_path": relative,
        "receipt_path": receipt_relative,
        "payload_sha256": digest,
        "item_count": _v4_global(_v4_scope, 'int')(payload["item_count"]),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _ResearchPeripheralStore_read_exact_body(_v4_scope, /, self, trade_date, source):
    normalized_date = _v4_global(_v4_scope, '_date')(trade_date)
    normalized_source = _v4_global(_v4_scope, '_source')(source)
    relative = self._relative(normalized_date, normalized_source)
    receipt_relative = self._receipt_relative(normalized_date, normalized_source)
    artifact_path = self._path(relative)
    receipt_path = self._path(receipt_relative)
    manifest = self._manifest()
    tracked = relative in manifest
    if not artifact_path.exists() and not receipt_path.exists() and not tracked:
        return None
    if not artifact_path.is_file() or not receipt_path.is_file() or not tracked:
        raise _v4_global(_v4_scope, 'ValueError')("research peripheral manifest or receipt mismatch")
    payload = self._read(relative)
    digest = _v4_global(_v4_scope, '_sha256')(payload)
    expected_receipt = self._receipt(payload, digest)
    if (
        manifest.get(relative) != digest
        or not self._receipt_matches(payload, digest, self._read(receipt_relative))
        or _v4_global(_v4_scope, 'validate_research_peripheral')(
            payload,
            expected_trade_date=normalized_date,
            expected_source=normalized_source,
        )
        != (normalized_date, normalized_source)
    ):
        raise _v4_global(_v4_scope, 'ValueError')("research peripheral manifest or receipt mismatch")
    return payload
