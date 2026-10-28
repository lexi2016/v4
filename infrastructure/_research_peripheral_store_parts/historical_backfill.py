"""infrastructure.research_peripheral_store: historical_backfill (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _ResearchPeripheralStore_publish_historical_backfill_body(_v4_scope, /, self, payload):
    """Publish a development-only retrospective source artifact.

        Historical backfills live outside the exact-date live artifact so they
        cannot silently replace an original-time capture.  The payload itself
        carries the explicit ``HISTORICAL_BACKFILL`` identity and remains
        research-only.
        """
    trade_date, source = _v4_global(_v4_scope, 'validate_research_peripheral')(payload)
    if payload.get("capture_origin") != "HISTORICAL_BACKFILL" or payload.get("original_time_capture") is not False:
        raise _v4_global(_v4_scope, 'ValueError')("historical backfill identity is required")
    relative = self._historical_backfill_relative(trade_date, source)
    receipt_relative = self._historical_backfill_receipt_relative(trade_date, source)
    digest = _v4_global(_v4_scope, '_sha256')(payload)
    receipt = {
        "schema_version": _v4_global(_v4_scope, '_BACKFILL_RECEIPT_SCHEMA_VERSION'),
        "trade_date": trade_date,
        "source": source,
        "payload_path": relative,
        "payload_sha256": digest,
        "item_count": _v4_global(_v4_scope, 'int')(payload["item_count"]),
        "capture_origin": "HISTORICAL_BACKFILL",
        "original_time_capture": False,
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    with self._lock():
        manifest = self._manifest()
        existing = manifest.get(relative)
        artifact_path = self._path(relative)
        receipt_path = self._path(receipt_relative)
        if existing and existing != digest:
            raise _v4_global(_v4_scope, 'ValueError')("conflicting historical backfill re-import")
        if existing:
            if (
                not artifact_path.is_file()
                or _v4_global(_v4_scope, '_sha256')(self._read(relative)) != digest
                or not receipt_path.is_file()
                or self._read(receipt_relative) != receipt
            ):
                raise _v4_global(_v4_scope, 'ValueError')("historical backfill integrity mismatch")
        else:
            if artifact_path.exists() or receipt_path.exists():
                raise _v4_global(_v4_scope, 'ValueError')("orphan historical backfill artifact or receipt")
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
        "capture_origin": "HISTORICAL_BACKFILL",
        "original_time_capture": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _ResearchPeripheralStore_read_historical_backfill_body(_v4_scope, /, self, trade_date, source):
    trade_date = _v4_global(_v4_scope, '_date')(trade_date)
    source = _v4_global(_v4_scope, '_source')(source)
    relative = self._historical_backfill_relative(trade_date, source)
    receipt_relative = self._historical_backfill_receipt_relative(trade_date, source)
    if not self._path(relative).is_file() or not self._path(receipt_relative).is_file():
        return None
    payload = self._read(relative)
    _v4_global(_v4_scope, 'validate_research_peripheral')(
        payload,
        expected_trade_date=trade_date,
        expected_source=source,
    )
    if payload.get("capture_origin") != "HISTORICAL_BACKFILL" or payload.get("original_time_capture") is not False:
        raise _v4_global(_v4_scope, 'ValueError')("historical backfill identity is unsafe")
    digest = _v4_global(_v4_scope, '_sha256')(payload)
    manifest = self._manifest()
    receipt = self._read(receipt_relative)
    expected_receipt = {
        "schema_version": _v4_global(_v4_scope, '_BACKFILL_RECEIPT_SCHEMA_VERSION'),
        "trade_date": trade_date,
        "source": source,
        "payload_path": relative,
        "payload_sha256": digest,
        "item_count": _v4_global(_v4_scope, 'int')(payload["item_count"]),
        "capture_origin": "HISTORICAL_BACKFILL",
        "original_time_capture": False,
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if manifest.get(relative) != digest or receipt != expected_receipt:
        raise _v4_global(_v4_scope, 'ValueError')("historical backfill manifest or receipt mismatch")
    return payload
