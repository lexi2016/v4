"""infrastructure.research_store: archive_products (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _ResearchArchiveStore__receipt_body(_v4_scope, /, payload, digest):
    archive_date = _v4_global(_v4_scope, 'str')(payload["archive_date"])
    return {
        "schema_version": "v3_5.research_archive_receipt.v1",
        "archive_date": archive_date,
        "payload_path": _v4_global(_v4_scope, 'ResearchArchiveStore')._relative(archive_date),
        "payload_sha256": digest,
        "source_input_sha256": payload["source_input_sha256"],
        "article_count": payload["article_count"],
        "stock_pool_count": payload["stock_pool_count"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _ResearchArchiveStore__day_receipt_body(_v4_scope, /, payload, digest):
    archive_date = _v4_global(_v4_scope, 'str')(payload["archive_date"])
    return {
        "schema_version": "v3_5.research_day_product_receipt.v1",
        "contract_id": _v4_global(_v4_scope, 'PRODUCT_SCHEMA_VERSION'),
        "archive_date": archive_date,
        "payload_path": _v4_global(_v4_scope, 'ResearchArchiveStore')._day_relative(archive_date),
        "payload_sha256": digest,
        "source_slots": _v4_global(_v4_scope, 'list')(payload["expected_slots"]),
        "counts": _v4_global(_v4_scope, 'dict')(payload["counts"]),
        "status": payload["status"],
        "authoritative": _v4_global(_v4_scope, 'bool')(payload["authoritative"]),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _ResearchArchiveStore_publish_body(_v4_scope, /, self, payload, *, mode):
    archive_date = _v4_global(_v4_scope, 'validate_research_archive')(payload)
    normalized_mode = _v4_global(_v4_scope, 'str')(mode).upper()
    if normalized_mode not in _v4_global(_v4_scope, '_MODES'):
        raise _v4_global(_v4_scope, 'ValueError')("research publication mode must be LIVE, REPLAY, or BACKFILL")
    relative = self._relative(archive_date)
    receipt_relative = self._receipt_relative(archive_date)
    digest = _v4_global(_v4_scope, '_sha256')(payload)
    receipt = self._receipt(payload, digest)
    latest_updated = False
    with self._lock():
        manifest = self._manifest()
        existing = manifest.get(relative)
        if existing and existing != digest:
            raise _v4_global(_v4_scope, 'ValueError')("conflicting research archive re-import")
        if existing:
            if (
                not self._path(relative).is_file()
                or _v4_global(_v4_scope, '_sha256')(self._read(relative)) != digest
                or not self._path(receipt_relative).is_file()
                or self._read(receipt_relative) != receipt
            ):
                raise _v4_global(_v4_scope, 'ValueError')("research archive integrity mismatch")
        else:
            if self._path(relative).exists() or self._path(receipt_relative).exists():
                raise _v4_global(_v4_scope, 'ValueError')("orphan research archive or receipt")
            self._write(relative, payload)
            self._write(receipt_relative, receipt)
            manifest[relative] = digest
            self._write_manifest(manifest)
        if normalized_mode == "LIVE":
            latest_updated = self._update_latest(archive_date, digest)
    return {
        "archive_date": archive_date,
        "mode": normalized_mode,
        "payload_path": relative,
        "receipt_path": receipt_relative,
        "payload_sha256": digest,
        "latest_updated": latest_updated,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _ResearchArchiveStore__update_latest_body(_v4_scope, /, self, archive_date, digest):
    relative = "research/latest.json"
    destination = self._path(relative)
    if destination.is_file():
        existing = self._read(relative)
        self._validate_pointer(existing)
        if _v4_global(_v4_scope, 'str')(existing["archive_date"]) > archive_date:
            raise _v4_global(_v4_scope, 'ValueError')("LIVE research publication cannot move latest backwards")
        if _v4_global(_v4_scope, 'str')(existing["archive_date"]) == archive_date and existing["payload_sha256"] == digest:
            return False
    body = {
        "schema_version": "v3_5.research_latest_pointer.v1",
        "archive_date": archive_date,
        "payload_path": self._relative(archive_date),
        "payload_sha256": digest,
    }
    pointer = {**body, "pointer_semantic_hash": _v4_global(_v4_scope, '_sha256')(body)}
    self._write(relative, pointer)
    return True


def _ResearchArchiveStore__validate_pointer_body(_v4_scope, /, pointer):
    if not _v4_global(_v4_scope, 'isinstance')(pointer, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(pointer) != {
        "schema_version",
        "archive_date",
        "payload_path",
        "payload_sha256",
        "pointer_semantic_hash",
    }:
        raise _v4_global(_v4_scope, 'ValueError')("invalid research latest pointer")
    archive_date = _v4_global(_v4_scope, '_date')(_v4_global(_v4_scope, 'str')(pointer.get("archive_date") or ""))
    body = {key: value for key, value in pointer.items() if key != "pointer_semantic_hash"}
    if (
        pointer.get("schema_version") != "v3_5.research_latest_pointer.v1"
        or pointer.get("payload_path") != _v4_global(_v4_scope, 'ResearchArchiveStore')._relative(archive_date)
        or not _v4_global(_v4_scope, '_SHA256').fullmatch(_v4_global(_v4_scope, 'str')(pointer.get("payload_sha256") or ""))
        or pointer.get("pointer_semantic_hash") != _v4_global(_v4_scope, '_sha256')(body)
    ):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research latest pointer")


def _ResearchArchiveStore_read_exact_body(_v4_scope, /, self, archive_date):
    archive_date = _v4_global(_v4_scope, '_date')(archive_date)
    relative = self._relative(archive_date)
    receipt_relative = self._receipt_relative(archive_date)
    payload_path = self._path(relative)
    receipt_path = self._path(receipt_relative)
    manifest = self._manifest()
    if not payload_path.is_file():
        if payload_path.exists() or receipt_path.exists() or relative in manifest:
            raise _v4_global(_v4_scope, 'ValueError')("research archive manifest or receipt mismatch")
        return None
    payload = self._read(relative)
    if payload.get("schema_version") == _v4_global(_v4_scope, 'PRODUCT_SCHEMA_VERSION'):
        raise _v4_global(_v4_scope, 'ValueError')("generic research archive path contains a day product")
    digest = _v4_global(_v4_scope, '_sha256')(payload)
    if (
        manifest.get(relative) != digest
        or not receipt_path.is_file()
        or self._read(receipt_relative) != self._receipt(payload, digest)
        or _v4_global(_v4_scope, 'validate_research_archive')(payload) != archive_date
    ):
        raise _v4_global(_v4_scope, 'ValueError')("research archive manifest or receipt mismatch")
    return payload


def _ResearchArchiveStore_publish_day_product_body(_v4_scope, /, self, payload):
    """Publish a complete exact-date day product in its own namespace.

        The legacy generic archive and its receipt remain authoritative at
        ``research/archives/{date}.json``.  Day products use a separate
        manifest key and pointer namespace, so publishing a full-day product
        cannot overwrite or reinterpret a same-date generic archive.
        """

    archive_date = _v4_global(_v4_scope, 'validate_research_day_product')(payload)
    relative = self._day_relative(archive_date)
    receipt_relative = self._day_receipt_relative(archive_date)
    digest = _v4_global(_v4_scope, '_sha256')(payload)
    receipt = self._day_receipt(payload, digest)
    latest_updated = False
    current_updated = False
    with self._lock():
        manifest = self._manifest()
        existing = manifest.get(relative)
        payload_path = self._path(relative)
        receipt_path = self._path(receipt_relative)
        if existing and existing != digest:
            raise _v4_global(_v4_scope, 'ValueError')("conflicting research day product re-import")
        if existing:
            existing_payload = self._read(relative) if payload_path.is_file() else {}
            if existing_payload.get("schema_version") != _v4_global(_v4_scope, 'PRODUCT_SCHEMA_VERSION'):
                raise _v4_global(_v4_scope, 'ValueError')("existing generic archive blocks day product")
            if (
                not payload_path.is_file()
                or _v4_global(_v4_scope, '_sha256')(existing_payload) != digest
                or not receipt_path.is_file()
                or self._read(receipt_relative) != receipt
            ):
                raise _v4_global(_v4_scope, 'ValueError')("research day product manifest or receipt mismatch")
        else:
            if payload_path.exists() or receipt_path.exists():
                raise _v4_global(_v4_scope, 'ValueError')("orphan research archive or receipt")
            self._write(relative, payload)
            self._write(receipt_relative, receipt)
            manifest[relative] = digest
            self._write_manifest(manifest)
        latest_updated = self._update_day_latest(archive_date, digest)
        current_updated = self._update_day_current(archive_date, digest)
    current_relative = self._day_current_relative()
    current = self._read(current_relative)
    return {
        "archive_date": archive_date,
        "payload_path": relative,
        "receipt_path": receipt_relative,
        "payload_sha256": digest,
        "receipt_sha256": _v4_global(_v4_scope, '_sha256')(receipt),
        "manifest_sha256": _v4_global(_v4_scope, '_sha256')(self._manifest()),
        "latest_updated": latest_updated,
        "current_updated": current_updated,
        "current_path": current_relative,
        "current_sha256": _v4_global(_v4_scope, '_sha256')(current),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _ResearchArchiveStore__update_day_latest_body(_v4_scope, /, self, archive_date, digest):
    relative = self._day_latest_relative()
    destination = self._path(relative)
    if destination.is_file():
        existing = self._read(relative)
        self._validate_day_latest_pointer(existing)
        existing_position = _v4_global(_v4_scope, 'str')(existing["archive_date"])
        if existing_position > archive_date:
            raise _v4_global(_v4_scope, 'ValueError')("research day product cannot move latest backwards")
        if (
            existing_position == archive_date
            and existing["payload_sha256"] == digest
        ):
            return False
    elif destination.exists():
        raise _v4_global(_v4_scope, 'ValueError')("invalid research latest pointer")
    body = {
        "schema_version": "v3_5.research_day_latest_pointer.v1",
        "archive_date": archive_date,
        "payload_path": self._day_relative(archive_date),
        "payload_sha256": digest,
    }
    self._write(relative, {**body, "pointer_semantic_hash": _v4_global(_v4_scope, '_sha256')(body)})
    return True


def _ResearchArchiveStore__validate_day_latest_pointer_body(_v4_scope, /, pointer):
    fields = {
        "schema_version",
        "archive_date",
        "payload_path",
        "payload_sha256",
        "pointer_semantic_hash",
    }
    if not _v4_global(_v4_scope, 'isinstance')(pointer, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(pointer) != fields:
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day latest pointer")
    archive_date = _v4_global(_v4_scope, '_date')(_v4_global(_v4_scope, 'str')(pointer.get("archive_date") or ""))
    body = {
        key: value for key, value in pointer.items() if key != "pointer_semantic_hash"
    }
    if (
        pointer.get("schema_version") != "v3_5.research_day_latest_pointer.v1"
        or pointer.get("payload_path") != _v4_global(_v4_scope, 'ResearchArchiveStore')._day_relative(archive_date)
        or not _v4_global(_v4_scope, '_SHA256').fullmatch(_v4_global(_v4_scope, 'str')(pointer.get("payload_sha256") or ""))
        or pointer.get("pointer_semantic_hash") != _v4_global(_v4_scope, '_sha256')(body)
    ):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research day latest pointer")


def _ResearchArchiveStore__update_day_current_body(_v4_scope, /, self, archive_date, digest):
    relative = self._day_current_relative()
    destination = self._path(relative)
    if destination.is_file():
        existing = self._read(relative)
        self._validate_current_pointer(existing)
        existing_position = _v4_global(_v4_scope, 'str')(existing["archive_date"])
        if existing_position > archive_date:
            raise _v4_global(_v4_scope, 'ValueError')("research day product cannot move current backwards")
        if (
            existing_position == archive_date
            and existing["payload_sha256"] == digest
        ):
            return False
    elif destination.exists():
        raise _v4_global(_v4_scope, 'ValueError')("invalid research current pointer")
    body = {
        "schema_version": "v3_5.research_day_current_pointer.v1",
        "archive_date": archive_date,
        "payload_path": self._day_relative(archive_date),
        "payload_sha256": digest,
    }
    self._write(relative, {**body, "pointer_semantic_hash": _v4_global(_v4_scope, '_sha256')(body)})
    return True


def _ResearchArchiveStore__validate_current_pointer_body(_v4_scope, /, pointer):
    fields = {
        "schema_version",
        "archive_date",
        "payload_path",
        "payload_sha256",
        "pointer_semantic_hash",
    }
    if not _v4_global(_v4_scope, 'isinstance')(pointer, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(pointer) != fields:
        raise _v4_global(_v4_scope, 'ValueError')("invalid research current pointer")
    archive_date = _v4_global(_v4_scope, '_date')(_v4_global(_v4_scope, 'str')(pointer.get("archive_date") or ""))
    body = {
        key: value for key, value in pointer.items() if key != "pointer_semantic_hash"
    }
    if (
        pointer.get("schema_version") != "v3_5.research_day_current_pointer.v1"
        or pointer.get("payload_path") != _v4_global(_v4_scope, 'ResearchArchiveStore')._day_relative(archive_date)
        or not _v4_global(_v4_scope, '_SHA256').fullmatch(_v4_global(_v4_scope, 'str')(pointer.get("payload_sha256") or ""))
        or pointer.get("pointer_semantic_hash") != _v4_global(_v4_scope, '_sha256')(body)
    ):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research current pointer")


def _ResearchArchiveStore_read_day_exact_body(_v4_scope, /, self, archive_date):
    archive_date = _v4_global(_v4_scope, '_date')(archive_date)
    relative = self._day_relative(archive_date)
    receipt_relative = self._day_receipt_relative(archive_date)
    payload_path = self._path(relative)
    receipt_path = self._path(receipt_relative)
    manifest = self._manifest()
    if not payload_path.is_file():
        if payload_path.exists() or receipt_path.exists() or relative in manifest:
            raise _v4_global(_v4_scope, 'ValueError')("research day product manifest or receipt mismatch")
        return None
    payload = self._read(relative)
    if payload.get("schema_version") != _v4_global(_v4_scope, 'PRODUCT_SCHEMA_VERSION'):
        return None
    digest = _v4_global(_v4_scope, '_sha256')(payload)
    receipt = self._day_receipt(payload, digest)
    if (
        manifest.get(relative) != digest
        or not receipt_path.is_file()
        or self._read(receipt_relative) != receipt
        or _v4_global(_v4_scope, 'validate_research_day_product')(payload) != archive_date
    ):
        raise _v4_global(_v4_scope, 'ValueError')("research day product manifest or receipt mismatch")
    return payload


def _ResearchArchiveStore_read_day_latest_body(_v4_scope, /, self):
    relative = self._day_latest_relative()
    pointer_path = self._path(relative)
    if not pointer_path.is_file():
        if pointer_path.exists():
            raise _v4_global(_v4_scope, 'ValueError')("invalid research latest pointer")
        return None
    pointer = self._read(relative)
    self._validate_day_latest_pointer(pointer)
    payload = self.read_day_exact(_v4_global(_v4_scope, 'str')(pointer["archive_date"]))
    if payload is None or _v4_global(_v4_scope, '_sha256')(payload) != pointer["payload_sha256"]:
        return None
    return payload


def _ResearchArchiveStore_read_day_current_body(_v4_scope, /, self):
    relative = self._day_current_relative()
    pointer_path = self._path(relative)
    if not pointer_path.is_file():
        if pointer_path.exists():
            raise _v4_global(_v4_scope, 'ValueError')("invalid research current pointer")
        return None
    pointer = self._read(relative)
    self._validate_current_pointer(pointer)
    payload = self.read_day_exact(_v4_global(_v4_scope, 'str')(pointer["archive_date"]))
    if payload is None or _v4_global(_v4_scope, '_sha256')(payload) != pointer["payload_sha256"]:
        raise _v4_global(_v4_scope, 'ValueError')("research current pointer target mismatch")
    return payload


def _ResearchArchiveStore_read_latest_body(_v4_scope, /, self):
    relative = "research/latest.json"
    pointer_path = self._path(relative)
    if not pointer_path.is_file():
        if pointer_path.exists():
            raise _v4_global(_v4_scope, 'ValueError')("invalid research latest pointer")
        return None
    pointer = self._read(relative)
    self._validate_pointer(pointer)
    payload = self.read_exact(_v4_global(_v4_scope, 'str')(pointer["archive_date"]))
    if payload is None or _v4_global(_v4_scope, '_sha256')(payload) != pointer["payload_sha256"]:
        raise _v4_global(_v4_scope, 'ValueError')("research latest pointer target mismatch")
    return payload
