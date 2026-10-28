"""infrastructure.research_peripheral_store: replacement (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _ResearchPeripheralStore_replace_body(_v4_scope, /, self, payload, *, expected_sha256, reason):
    """CAS-replace one exact source while preserving its previous payload."""
    trade_date, source = _v4_global(_v4_scope, 'validate_research_peripheral')(payload)
    expected = _v4_global(_v4_scope, 'str')(expected_sha256 or "").strip().lower()
    normalized_reason = _v4_global(_v4_scope, 'str')(reason or "").strip()
    if not _v4_global(_v4_scope, '_SHA256').fullmatch(expected):
        raise _v4_global(_v4_scope, 'ValueError')("research peripheral expected SHA must be sha256")
    if not normalized_reason:
        raise _v4_global(_v4_scope, 'ValueError')("research peripheral replacement reason is required")
    relative = self._relative(trade_date, source)
    receipt_relative = self._receipt_relative(trade_date, source)
    digest = _v4_global(_v4_scope, '_sha256')(payload)
    replacement_receipt = self._receipt(payload, digest)
    with self._lock():
        manifest = self._manifest()
        if manifest.get(relative) != expected:
            raise _v4_global(_v4_scope, 'ValueError')("research peripheral expected SHA mismatch")
        artifact_path = self._path(relative)
        receipt_path = self._path(receipt_relative)
        if not artifact_path.is_file() or not receipt_path.is_file():
            raise _v4_global(_v4_scope, 'ValueError')("research peripheral replacement source is incomplete")
        previous_payload = self._read(relative)
        previous_digest = _v4_global(_v4_scope, '_sha256')(previous_payload)
        if (
            previous_digest != expected
            or not self._receipt_matches(
                previous_payload,
                previous_digest,
                self._read(receipt_relative),
            )
            or _v4_global(_v4_scope, 'validate_research_peripheral')(
                previous_payload,
                expected_trade_date=trade_date,
                expected_source=source,
            )
            != (trade_date, source)
        ):
            raise _v4_global(_v4_scope, 'ValueError')("research peripheral replacement integrity mismatch")
        if digest == previous_digest:
            return {
                "trade_date": trade_date,
                "source": source,
                "payload_path": relative,
                "receipt_path": receipt_relative,
                "payload_sha256": digest,
                "replaced": False,
                "previous_payload_path": "",
                "supersession_receipt_path": "",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        history_relative = self._history_relative(
            trade_date, source, previous_digest
        )
        supersession_relative = self._supersession_relative(
            trade_date, source, digest
        )
        history_path = self._path(history_relative)
        supersession_path = self._path(supersession_relative)
        if history_path.exists() and (
            not history_path.is_file()
            or self._read(history_relative) != previous_payload
        ):
            raise _v4_global(_v4_scope, 'ValueError')("research peripheral history conflict")
        supersession = {
            "schema_version": "v3_5.research_peripheral_supersession.v1",
            "trade_date": trade_date,
            "source": source,
            "payload_path": relative,
            "payload_sha256": digest,
            "previous_payload_path": history_relative,
            "previous_payload_sha256": previous_digest,
            "reason": normalized_reason,
            "write_policy": "read_only",
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        if supersession_path.exists() and (
            not supersession_path.is_file()
            or self._read(supersession_relative) != supersession
        ):
            raise _v4_global(_v4_scope, 'ValueError')("research peripheral supersession conflict")
        if not history_path.exists():
            self._write(history_relative, previous_payload)
        if not supersession_path.exists():
            self._write(supersession_relative, supersession)
        self._write(relative, payload)
        self._write(receipt_relative, replacement_receipt)
        manifest[relative] = digest
        self._write_manifest(manifest)
    return {
        "trade_date": trade_date,
        "source": source,
        "payload_path": relative,
        "receipt_path": receipt_relative,
        "payload_sha256": digest,
        "replaced": True,
        "previous_payload_path": history_relative,
        "supersession_receipt_path": supersession_relative,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
