"""infrastructure.research_store: hourly_publish (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _HourlyResearchStore__transform_validation_relative_body(_v4_scope, /, archive_date, slot, mode, source_input_sha256, transformer_identity_sha256):
    validation_key = _v4_global(_v4_scope, '_sha256')(
        {
            "source_input_sha256": source_input_sha256,
            "transformer_identity_sha256": transformer_identity_sha256,
        }
    )
    return (
        "receipts/research/hourly/transform-validation/"
        f"{mode.lower()}/{archive_date}/{slot}/"
        f"{validation_key}.json"
    )


def _HourlyResearchStore__receipt_body(_v4_scope, /, payload, digest, *, slot, mode):
    archive_date = _v4_global(_v4_scope, 'str')(payload["archive_date"])
    return {
        "schema_version": "v3_5.hourly_research_receipt.v1",
        "archive_date": archive_date,
        "slot": slot,
        "mode": mode,
        "payload_path": _v4_global(_v4_scope, 'HourlyResearchStore')._relative(
            archive_date, slot, mode
        ),
        "payload_sha256": digest,
        "source_input_sha256": payload["source_input_sha256"],
        "article_count": payload["article_count"],
        "stock_pool_count": payload["stock_pool_count"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _HourlyResearchStore__transform_validation_body(_v4_scope, /, payload, digest, *, slot, mode, transformer_identity_sha256):
    archive_date = _v4_global(_v4_scope, 'str')(payload["archive_date"])
    source_input_sha256 = _v4_global(_v4_scope, 'str')(payload["source_input_sha256"])
    return {
        "schema_version": "v3_5.hourly_research_transform_validation.v1",
        "archive_date": archive_date,
        "slot": slot,
        "mode": mode,
        "payload_path": _v4_global(_v4_scope, 'HourlyResearchStore')._relative(
            archive_date,
            slot,
            mode,
        ),
        "payload_sha256": digest,
        "source_input_sha256": source_input_sha256,
        "transformer_identity_sha256": transformer_identity_sha256,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _HourlyResearchStore_publish_body(_v4_scope, /, self, payload, *, slot, mode, transformer_identity_sha256):
    archive_date = _v4_global(_v4_scope, 'validate_research_archive')(payload)
    normalized_slot = _v4_global(_v4_scope, '_slot')(slot)
    normalized_mode = _v4_global(_v4_scope, 'str')(mode).upper()
    if normalized_mode not in _v4_global(_v4_scope, '_MODES'):
        raise _v4_global(_v4_scope, 'ValueError')(
            "hourly research mode must be LIVE, REPLAY, or BACKFILL"
        )
    normalized_transformer_sha = None
    if transformer_identity_sha256 is not None:
        normalized_transformer_sha = _v4_global(_v4_scope, 'str')(
            transformer_identity_sha256
        ).lower()
        if not _v4_global(_v4_scope, '_SHA256').fullmatch(normalized_transformer_sha):
            raise _v4_global(_v4_scope, 'ValueError')(
                "hourly research transformer identity must be SHA-256"
            )
    relative = self._relative(
        archive_date, normalized_slot, normalized_mode
    )
    receipt_relative = self._receipt_relative(
        archive_date, normalized_slot, normalized_mode
    )
    digest = _v4_global(_v4_scope, '_sha256')(payload)
    receipt = self._receipt(
        payload,
        digest,
        slot=normalized_slot,
        mode=normalized_mode,
    )
    latest_updated = False
    with self._lock():
        manifest = self._manifest()
        existing = manifest.get(relative)
        if existing and existing != digest:
            raise _v4_global(_v4_scope, 'ValueError')("conflicting hourly research materialization")
        payload_path = self._path(relative)
        receipt_path = self._path(receipt_relative)
        interrupted_recovery = not existing and payload_path.exists()
        if normalized_mode == "LIVE" and not (
            existing or interrupted_recovery
        ):
            self._assert_latest_not_backwards(
                archive_date, normalized_slot
            )
        if existing:
            if (
                not payload_path.is_file()
                or _v4_global(_v4_scope, '_sha256')(self._read(relative)) != digest
                or not receipt_path.is_file()
                or self._read(receipt_relative) != receipt
            ):
                raise _v4_global(_v4_scope, 'ValueError')("hourly research integrity mismatch")
        elif payload_path.exists():
            if (
                not payload_path.is_file()
                or _v4_global(_v4_scope, '_sha256')(self._read(relative)) != digest
            ):
                raise _v4_global(_v4_scope, 'ValueError')(
                    "conflicting interrupted hourly research artifact"
                )
            if receipt_path.exists():
                if (
                    not receipt_path.is_file()
                    or self._read(receipt_relative) != receipt
                ):
                    raise _v4_global(_v4_scope, 'ValueError')(
                        "conflicting interrupted hourly research receipt"
                    )
            else:
                self._write(receipt_relative, receipt)
            manifest[relative] = digest
            self._write_manifest(manifest)
        else:
            if receipt_path.exists():
                raise _v4_global(_v4_scope, 'ValueError')("orphan hourly research receipt")
            self._write(relative, payload)
            self._write(receipt_relative, receipt)
            manifest[relative] = digest
            self._write_manifest(manifest)
        if normalized_transformer_sha is not None:
            self._publish_transform_validation_locked(
                payload,
                digest,
                slot=normalized_slot,
                mode=normalized_mode,
                transformer_identity_sha256=normalized_transformer_sha,
            )
        if normalized_mode == "LIVE":
            if not self._latest_is_after(
                archive_date, normalized_slot
            ):
                latest_updated = self._update_latest(
                    archive_date, normalized_slot, digest
                )
    return {
        "archive_date": archive_date,
        "slot": normalized_slot,
        "mode": normalized_mode,
        "payload_path": relative,
        "receipt_path": receipt_relative,
        "payload_sha256": digest,
        "latest_updated": latest_updated,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _HourlyResearchStore__publish_transform_validation_locked_body(_v4_scope, /, self, payload, digest, *, slot, mode, transformer_identity_sha256):
    archive_date = _v4_global(_v4_scope, 'str')(payload["archive_date"])
    source_input_sha256 = _v4_global(_v4_scope, 'str')(payload["source_input_sha256"]).lower()
    validation = self._transform_validation(
        payload,
        digest,
        slot=slot,
        mode=mode,
        transformer_identity_sha256=transformer_identity_sha256,
    )
    validation_relative = self._transform_validation_relative(
        archive_date,
        slot,
        mode,
        source_input_sha256,
        transformer_identity_sha256,
    )
    validation_path = self._path(validation_relative)
    if validation_path.exists():
        if (
            not validation_path.is_file()
            or self._read(validation_relative) != validation
        ):
            raise _v4_global(_v4_scope, 'ValueError')(
                "hourly research transform validation mismatch"
            )
    else:
        self._write(validation_relative, validation)


def _HourlyResearchStore__latest_is_after_body(_v4_scope, /, self, archive_date, slot):
    destination = self._path("research/hourly/latest.json")
    if not destination.exists():
        return False
    if not destination.is_file():
        raise _v4_global(_v4_scope, 'ValueError')("invalid hourly research latest pointer")
    existing = self._read("research/hourly/latest.json")
    self._validate_pointer(existing)
    return (
        _v4_global(_v4_scope, 'str')(existing["archive_date"]),
        _v4_global(_v4_scope, 'str')(existing["slot"]),
    ) > (archive_date, slot)


def _HourlyResearchStore__update_latest_body(_v4_scope, /, self, archive_date, slot, digest):
    relative = "research/hourly/latest.json"
    destination = self._path(relative)
    if destination.is_file():
        existing = self._read(relative)
        self._validate_pointer(existing)
        existing_position = (
            _v4_global(_v4_scope, 'str')(existing["archive_date"]),
            _v4_global(_v4_scope, 'str')(existing["slot"]),
        )
        requested_position = (archive_date, slot)
        if existing_position > requested_position:
            raise _v4_global(_v4_scope, 'ValueError')(
                "LIVE hourly research publication cannot move latest backwards"
            )
        if (
            existing_position == requested_position
            and existing["payload_sha256"] == digest
        ):
            return False
    body = {
        "schema_version": "v3_5.hourly_research_latest_pointer.v1",
        "archive_date": archive_date,
        "slot": slot,
        "mode": "LIVE",
        "payload_path": self._relative(archive_date, slot, "LIVE"),
        "payload_sha256": digest,
    }
    pointer = {**body, "pointer_semantic_hash": _v4_global(_v4_scope, '_sha256')(body)}
    self._write(relative, pointer)
    return True


def _HourlyResearchStore__validate_pointer_body(_v4_scope, /, pointer):
    fields = {
        "schema_version",
        "archive_date",
        "slot",
        "mode",
        "payload_path",
        "payload_sha256",
        "pointer_semantic_hash",
    }
    if not _v4_global(_v4_scope, 'isinstance')(pointer, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(pointer) != fields:
        raise _v4_global(_v4_scope, 'ValueError')("invalid hourly research latest pointer")
    archive_date = _v4_global(_v4_scope, '_date')(_v4_global(_v4_scope, 'str')(pointer.get("archive_date") or ""))
    slot = _v4_global(_v4_scope, '_slot')(_v4_global(_v4_scope, 'str')(pointer.get("slot") or ""))
    body = {
        key: value
        for key, value in pointer.items()
        if key != "pointer_semantic_hash"
    }
    if (
        pointer.get("schema_version")
        != "v3_5.hourly_research_latest_pointer.v1"
        or pointer.get("mode") != "LIVE"
        or pointer.get("payload_path")
        != _v4_global(_v4_scope, 'HourlyResearchStore')._relative(archive_date, slot, "LIVE")
        or not _v4_global(_v4_scope, '_SHA256').fullmatch(_v4_global(_v4_scope, 'str')(pointer.get("payload_sha256") or ""))
        or pointer.get("pointer_semantic_hash") != _v4_global(_v4_scope, '_sha256')(body)
    ):
        raise _v4_global(_v4_scope, 'ValueError')("invalid hourly research latest pointer")
