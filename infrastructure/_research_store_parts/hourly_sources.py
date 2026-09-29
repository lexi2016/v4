"""infrastructure.research_store: hourly_sources (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global




def _HourlyResearchStore_read_latest_for_date_body(_v4_scope, /, self, archive_date, *, mode):
    """Read the highest verified slot for one exact date only."""

    archive_date = _v4_global(_v4_scope, '_date')(archive_date)
    slots = self.list_slots(archive_date, mode=mode)
    if not slots:
        return None
    slot = slots[-1]
    payload = self.read_exact(archive_date, slot, mode=mode)
    if payload is None:
        raise _v4_global(_v4_scope, 'ValueError')("hourly research manifest or receipt mismatch")
    return slot, payload


def _HourlyResearchStore_read_exact_body(_v4_scope, /, self, archive_date, slot, *, mode):
    archive_date = _v4_global(_v4_scope, '_date')(archive_date)
    normalized_slot = _v4_global(_v4_scope, '_slot')(slot)
    normalized_mode = _v4_global(_v4_scope, 'str')(mode).upper()
    if normalized_mode not in _v4_global(_v4_scope, '_MODES'):
        raise _v4_global(_v4_scope, 'ValueError')(
            "hourly research mode must be LIVE, REPLAY, or BACKFILL"
        )
    relative = self._relative(
        archive_date, normalized_slot, normalized_mode
    )
    receipt_relative = self._receipt_relative(
        archive_date, normalized_slot, normalized_mode
    )
    payload_path = self._path(relative)
    receipt_path = self._path(receipt_relative)
    manifest = self._manifest()
    if not payload_path.is_file():
        if payload_path.exists() or receipt_path.exists() or relative in manifest:
            raise _v4_global(_v4_scope, 'ValueError')("hourly research manifest or receipt mismatch")
        return None
    payload = self._read(relative)
    digest = _v4_global(_v4_scope, '_sha256')(payload)
    if (
        manifest.get(relative) != digest
        or not receipt_path.is_file()
        or self._read(receipt_relative)
        != self._receipt(
            payload,
            digest,
            slot=normalized_slot,
            mode=normalized_mode,
        )
        or _v4_global(_v4_scope, 'validate_research_archive')(payload) != archive_date
    ):
        raise _v4_global(_v4_scope, 'ValueError')("hourly research manifest or receipt mismatch")
    return payload


def _HourlyResearchStore_reuse_matching_source_body(_v4_scope, /, self, archive_date, slot, *, mode, source_input_sha256, transformer_identity_sha256):
    """Republish a finalized exact artifact only when its source is identical."""
    archive_date = _v4_global(_v4_scope, '_date')(archive_date)
    normalized_slot = _v4_global(_v4_scope, '_slot')(slot)
    normalized_mode = _v4_global(_v4_scope, 'str')(mode).upper()
    if normalized_mode not in _v4_global(_v4_scope, '_MODES'):
        raise _v4_global(_v4_scope, 'ValueError')(
            "hourly research mode must be LIVE, REPLAY, or BACKFILL"
        )
    normalized_source_sha = _v4_global(_v4_scope, 'str')(source_input_sha256).lower()
    if not _v4_global(_v4_scope, '_SHA256').fullmatch(normalized_source_sha):
        raise _v4_global(_v4_scope, 'ValueError')("hourly research source SHA must be SHA-256")
    normalized_transformer_sha = _v4_global(_v4_scope, 'str')(transformer_identity_sha256).lower()
    if not _v4_global(_v4_scope, '_SHA256').fullmatch(normalized_transformer_sha):
        raise _v4_global(_v4_scope, 'ValueError')("hourly research transformer identity must be SHA-256")
    relative = self._relative(
        archive_date,
        normalized_slot,
        normalized_mode,
    )
    validation_relative = self._transform_validation_relative(
        archive_date,
        normalized_slot,
        normalized_mode,
        normalized_source_sha,
        normalized_transformer_sha,
    )
    latest_updated = False
    with self._lock():
        validation_path = self._path(validation_relative)
        if not validation_path.is_file():
            if validation_path.exists():
                raise _v4_global(_v4_scope, 'ValueError')(
                    "invalid hourly research transform validation"
                )
            return None
        if relative not in self._manifest():
            raise _v4_global(_v4_scope, 'ValueError')("orphan hourly research transform validation")
        payload = self.read_exact(
            archive_date,
            normalized_slot,
            mode=normalized_mode,
        )
        if payload is None:
            raise _v4_global(_v4_scope, 'ValueError')("hourly research manifest or receipt mismatch")
        digest = _v4_global(_v4_scope, '_sha256')(payload)
        expected_validation = self._transform_validation(
            payload,
            digest,
            slot=normalized_slot,
            mode=normalized_mode,
            transformer_identity_sha256=normalized_transformer_sha,
        )
        if (
            payload["source_input_sha256"] != normalized_source_sha
            or self._read(validation_relative) != expected_validation
        ):
            raise _v4_global(_v4_scope, 'ValueError')(
                "hourly research transform validation mismatch"
            )
        if normalized_mode == "LIVE" and not self._latest_is_after(
            archive_date,
            normalized_slot,
        ):
            latest_updated = self._update_latest(
                archive_date,
                normalized_slot,
                digest,
            )
    return {
        "archive_date": archive_date,
        "slot": normalized_slot,
        "mode": normalized_mode,
        "payload_path": relative,
        "receipt_path": self._receipt_relative(
            archive_date,
            normalized_slot,
            normalized_mode,
        ),
        "payload_sha256": digest,
        "latest_updated": latest_updated,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _HourlyResearchStore_read_latest_body(_v4_scope, /, self):
    relative = "research/hourly/latest.json"
    pointer_path = self._path(relative)
    if not pointer_path.is_file():
        if pointer_path.exists():
            raise _v4_global(_v4_scope, 'ValueError')("invalid hourly research latest pointer")
        return None
    pointer = self._read(relative)
    self._validate_pointer(pointer)
    payload = self.read_exact(
        _v4_global(_v4_scope, 'str')(pointer["archive_date"]),
        _v4_global(_v4_scope, 'str')(pointer["slot"]),
        mode="LIVE",
    )
    if payload is None or _v4_global(_v4_scope, '_sha256')(payload) != pointer["payload_sha256"]:
        raise _v4_global(_v4_scope, 'ValueError')("hourly research latest pointer target mismatch")
    return payload
