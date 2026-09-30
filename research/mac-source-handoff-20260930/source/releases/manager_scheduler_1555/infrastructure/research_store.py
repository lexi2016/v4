"""Exact-date research archives with an explicit LIVE-only latest pointer."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo

from contracts.research_day_product import (
    MANAGER_DECISION_SCHEMA_VERSION,
    PRODUCT_SCHEMA_VERSION,
    RESEARCH_SUPPLY_TYPE,
    SELECTION_CONTRACT_ID,
    SELECTION_SCHEMA_VERSION,
    validate_selection_research_product,
    validate_manager_research_decision,
    validate_research_supply_envelope,
    validate_research_supply_receipt,
    validate_research_day_product,
)
from domains.research_day_product import (
    _selection_aware_hkt,
    append_selection_phase,
)
from contracts.research import validate_research_archive
from infrastructure.data_store import NativeDataStore, _date, _sha256
from infrastructure.owned_path import resolve_owned_path


_MODES = frozenset({"LIVE", "REPLAY", "BACKFILL"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _slot(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}", value):
        raise ValueError("research slot must use HHMM")
    if int(value[:2]) > 23 or int(value[2:]) > 59:
        raise ValueError("research slot must be a real time")
    return value


def _hourly_recovery_cutoff(archive_date: str, slot: str) -> str:
    """Return the exact PIT cutoff used by an hourly recovery receipt."""

    return datetime.strptime(f"{archive_date}{slot}", "%Y%m%d%H%M").replace(
        tzinfo=_SHANGHAI, second=59
    ).isoformat(timespec="seconds")


def _typed_hourly_source_receipts(
    value: Any,
    *,
    require_nonempty: bool = False,
) -> list[str]:
    """Validate the existing hourly source-receipt shape without coercion."""

    if not isinstance(value, list):
        raise ValueError("hourly research recovery source receipts are invalid")
    if require_nonempty and not value:
        raise ValueError("hourly research recovery source receipts are incomplete")
    if any(type(item) is not str or not item.strip() for item in value):
        raise ValueError("hourly research recovery source receipts are invalid")
    return list(value)


def _assert_hourly_recovery_projection_matches_source(
    actual_payload: Mapping[str, Any],
    supplied_payload: Mapping[str, Any],
) -> None:
    """Require direct recovery provenance to match the parsed source object.

    The direct CAS route receives a small structured projection from its
    caller.  The recovery file itself is authoritative for that projection;
    comparing the existing fields here prevents a caller from replacing a
    valid source manifest or receipt list with locally fabricated values.
    """

    fields = (
        "recovery",
        "trade_date",
        "slot",
        "source_path",
        "original_source_path",
        "original_source_sha256",
        "supersedes",
        "retry_of_sha256",
        "pit_cutoff",
        "capture_origin",
        "original_time_capture",
        "natural_execution_verified",
        "source_receipts",
        "source_manifest",
        "recovery_metadata",
        "repair_authorization",
        "cannot_confirm",
    )
    for field in fields:
        actual_present = field in actual_payload
        supplied_present = field in supplied_payload
        actual_value = actual_payload.get(field)
        supplied_value = supplied_payload.get(field)
        if (
            field == "repair_authorization"
            and actual_value is None
            and supplied_value is None
        ):
            # The late-recovery path legitimately has no explicit
            # authorization; absent and explicit null are equivalent there.
            continue
        if actual_present != supplied_present:
            raise ValueError(
                "hourly research recovery structured provenance mismatch"
            )
        if not actual_present:
            continue
        try:
            actual_encoded = json.dumps(
                actual_value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            supplied_encoded = json.dumps(
                supplied_value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "hourly research recovery structured provenance is invalid"
            ) from error
        if actual_encoded != supplied_encoded:
            raise ValueError(
                "hourly research recovery structured provenance mismatch"
            )


def _has_late_recovery_gap(value: Any) -> bool:
    return isinstance(value, list) and any(
        isinstance(gap, Mapping)
        and gap.get("reason") == "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT"
        for gap in value
    )


def _resolve_hourly_recovery_path(root: Path, value: Any, *, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"hourly research recovery {field} is invalid")
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    return resolve_owned_path(root, value).resolve(strict=False)


def validate_hourly_recovery_provenance(
    *,
    data_root: Path,
    archive_date: str,
    slot: str,
    recovery_path: Path,
    recovery_sha256: str,
    recovery_payload: Mapping[str, Any],
    expected_source_sha256: str | None = None,
    require_explicit_authorization: bool = False,
) -> dict[str, Any]:
    """Validate the complete recovery/source binding before a store mutation.

    The collector writes this document once.  Both the runner and the direct
    store CAS route use the same narrow checks so a direct caller cannot omit
    the original input receipt and still replace a formal hourly artifact.
    """

    archive_date = _date(str(archive_date))
    normalized_slot = _slot(str(slot))
    recovery_path = Path(recovery_path).resolve(strict=False)
    expected_parent = resolve_owned_path(
        Path(data_root), f"research/incoming/{archive_date}"
    ).resolve(strict=False)
    recovery_match = re.fullmatch(
        rf"{re.escape(normalized_slot)}\.recovery-([0-9a-f]{{16}})\.json",
        recovery_path.name,
    )
    if (
        recovery_match is None
        or recovery_path.parent != expected_parent
        or not recovery_path.is_file()
        or not isinstance(recovery_sha256, str)
        or not _SHA256.fullmatch(recovery_sha256.lower())
        or not recovery_sha256.lower().startswith(recovery_match.group(1))
    ):
        raise ValueError("hourly research recovery source identity is invalid")
    try:
        recovery_bytes = recovery_path.read_bytes()
        actual_recovery_sha = hashlib.sha256(recovery_bytes).hexdigest()
    except OSError as error:
        raise ValueError("hourly research recovery source identity is invalid") from error
    normalized_recovery_sha = str(recovery_sha256).lower()
    if (
        actual_recovery_sha != normalized_recovery_sha
        or not actual_recovery_sha.startswith(recovery_match.group(1))
    ):
        raise ValueError("hourly research recovery source bytes SHA mismatch")
    try:
        actual_recovery_payload = json.loads(recovery_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("hourly research recovery source payload is invalid") from error
    if not isinstance(actual_recovery_payload, Mapping):
        raise ValueError("hourly research recovery source payload is invalid")
    _assert_hourly_recovery_projection_matches_source(
        actual_recovery_payload,
        recovery_payload,
    )
    actual_late_recovery_gap = _has_late_recovery_gap(
        actual_recovery_payload.get("cannot_confirm")
    )
    if not isinstance(recovery_payload, Mapping):
        raise ValueError("hourly research recovery provenance is invalid")
    if actual_late_recovery_gap != _has_late_recovery_gap(
        recovery_payload.get("cannot_confirm")
    ):
        raise ValueError("hourly research recovery late provenance mismatch")
    if recovery_payload.get("recovery") is not True:
        raise ValueError("hourly research recovery provenance is invalid")

    metadata = recovery_payload.get("recovery_metadata")
    manifest = recovery_payload.get("source_manifest")
    if not isinstance(metadata, Mapping) or not isinstance(manifest, Mapping):
        raise ValueError("hourly research recovery provenance is invalid")

    cutoff = _hourly_recovery_cutoff(archive_date, normalized_slot)
    supersedes = metadata.get("supersedes")
    retry_of = metadata.get("retry_of_sha256")
    original_sha = metadata.get("original_source_sha256")
    if (
        not isinstance(supersedes, str)
        or not _SHA256.fullmatch(supersedes.lower())
        or not isinstance(retry_of, str)
        or not _SHA256.fullmatch(retry_of.lower())
        or not isinstance(original_sha, str)
        or not _SHA256.fullmatch(original_sha.lower())
        or not (supersedes.lower() == retry_of.lower() == original_sha.lower())
    ):
        raise ValueError("hourly research recovery source SHA provenance is invalid")
    supersedes = supersedes.lower()
    original_sha = original_sha.lower()

    if (
        recovery_payload.get("trade_date") != archive_date
        or recovery_payload.get("slot") != normalized_slot
        or recovery_payload.get("supersedes") != supersedes
        or recovery_payload.get("retry_of_sha256") != supersedes
        or recovery_payload.get("original_source_sha256") != original_sha
        or recovery_payload.get("capture_origin") != "LATE_RECOVERY"
        or recovery_payload.get("original_time_capture") is not False
        or recovery_payload.get("natural_execution_verified") is not False
        or recovery_payload.get("pit_cutoff") != cutoff
    ):
        raise ValueError("hourly research recovery provenance is invalid")

    manifest_receipts = _typed_hourly_source_receipts(
        manifest.get("source_receipts"),
        require_nonempty=True,
    )
    payload_receipts = _typed_hourly_source_receipts(
        recovery_payload.get("source_receipts"),
        require_nonempty=True,
    )
    metadata_receipts = _typed_hourly_source_receipts(
        metadata.get("source_receipts"),
        require_nonempty=True,
    )
    if not (manifest_receipts == payload_receipts == metadata_receipts):
        raise ValueError("hourly research recovery source receipts mismatch")
    if (
        manifest.get("trade_date") != archive_date
        or manifest.get("hourly_slot") != normalized_slot
        or manifest.get("pit_cutoff") != cutoff
        or manifest.get("capture_origin") != "LATE_RECOVERY"
        or manifest.get("original_time_capture") is not False
        or manifest.get("natural_execution_verified") is not False
    ):
        raise ValueError("hourly research recovery manifest provenance is invalid")
    if (
        metadata.get("trade_date") != archive_date
        or metadata.get("slot") != normalized_slot
        or metadata.get("pit_cutoff") != cutoff
        or metadata.get("capture_origin") != "LATE_RECOVERY"
        or metadata.get("original_time_capture") is not False
        or metadata.get("natural_execution_verified") is not False
    ):
        raise ValueError("hourly research recovery metadata is invalid")

    canonical_path = resolve_owned_path(
        Path(data_root), f"research/incoming/{archive_date}/{normalized_slot}.json"
    ).resolve(strict=False)
    original_path = _resolve_hourly_recovery_path(
        Path(data_root), metadata.get("original_source_path"), field="original_source_path"
    )
    if original_path != canonical_path or not original_path.is_file():
        raise ValueError("hourly research recovery original source path is invalid")
    actual_original_sha = hashlib.sha256(original_path.read_bytes()).hexdigest()
    if actual_original_sha != original_sha:
        raise ValueError("hourly research recovery original source SHA mismatch")
    if expected_source_sha256 is not None:
        expected = str(expected_source_sha256 or "").lower()
        if not _SHA256.fullmatch(expected) or expected != original_sha:
            raise ValueError("hourly research recovery expected source SHA mismatch")

    top_original_path = recovery_payload.get("original_source_path")
    if (
        _resolve_hourly_recovery_path(
            Path(data_root), top_original_path, field="original_source_path"
        )
        != canonical_path
        or recovery_payload.get("original_source_sha256") != original_sha
        or recovery_payload.get("source_path") != canonical_path.as_posix()
    ):
        raise ValueError("hourly research recovery original source provenance is invalid")
    if metadata.get("source_path") != canonical_path.as_posix():
        raise ValueError("hourly research recovery source path is invalid")

    authorization = metadata.get("repair_authorization")
    top_authorization = recovery_payload.get("repair_authorization")
    if authorization is not None:
        if not isinstance(authorization, Mapping) or top_authorization != authorization:
            raise ValueError("hourly research recovery authorization is invalid")
        if (
            authorization.get("kind") != "EXPLICIT_EXPECTED_OLD_INPUT_SHA256"
            or authorization.get("expected_old_input_sha256") != original_sha
            or authorization.get("canonical_path") != canonical_path.as_posix()
        ):
            raise ValueError("hourly research recovery authorization is invalid")
    elif top_authorization is not None:
        raise ValueError("hourly research recovery authorization is invalid")
    late_recovery_gap = _has_late_recovery_gap(
        recovery_payload.get("cannot_confirm")
    )
    if authorization is None and (require_explicit_authorization or not late_recovery_gap):
        raise ValueError("hourly research recovery authorization is required")

    return {
        "original_source_path": canonical_path.as_posix(),
        "original_source_sha256": original_sha,
        "source_receipts": manifest_receipts,
        "repair_authorization": dict(authorization) if authorization is not None else None,
        "pit_cutoff": cutoff,
    }



class ResearchArchiveStore(NativeDataStore):
    def _path(self, relative: str) -> Path:
        return resolve_owned_path(self.root, relative)

    @staticmethod
    def _relative(archive_date: str) -> str:
        return f"research/archives/{archive_date}.json"

    @staticmethod
    def _receipt_relative(archive_date: str) -> str:
        return f"receipts/research/archives/{archive_date}.json"

    @staticmethod
    def _day_relative(archive_date: str) -> str:
        """Return the physical namespace owned by exact-day products.

        Generic hourly/archive material uses ``research/archives``.  A day
        product is a different contract and must never claim that same date
        key, because a legacy archive may already exist there.
        """

        return f"research/day/archives/{archive_date}.json"

    @staticmethod
    def _day_receipt_relative(archive_date: str) -> str:
        return f"receipts/research/day/archives/{archive_date}.json"

    @staticmethod
    def _day_latest_relative() -> str:
        return "research/day/latest.json"

    @staticmethod
    def _day_current_relative() -> str:
        return "research/day/current.json"

    @staticmethod
    def _receipt(payload: Mapping[str, Any], digest: str) -> dict[str, Any]:
        archive_date = str(payload["archive_date"])
        return {
            "schema_version": "v3_5.research_archive_receipt.v1",
            "archive_date": archive_date,
            "payload_path": ResearchArchiveStore._relative(archive_date),
            "payload_sha256": digest,
            "source_input_sha256": payload["source_input_sha256"],
            "article_count": payload["article_count"],
            "stock_pool_count": payload["stock_pool_count"],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    @staticmethod
    def _history_relative(archive_date: str, digest: str) -> str:
        return f"research/archives/history/{archive_date}/{digest}.json"

    @staticmethod
    def _history_receipt_relative(archive_date: str, digest: str) -> str:
        return f"receipts/research/archives/history/{archive_date}/{digest}.json"

    @staticmethod
    def _supersession_relative(archive_date: str, digest: str) -> str:
        return f"receipts/research/archives/supersessions/{archive_date}/{digest}.json"

    @staticmethod
    def _day_receipt(payload: Mapping[str, Any], digest: str) -> dict[str, Any]:
        archive_date = str(payload["archive_date"])
        return {
            "schema_version": "v3_5.research_day_product_receipt.v1",
            "contract_id": PRODUCT_SCHEMA_VERSION,
            "archive_date": archive_date,
            "payload_path": ResearchArchiveStore._day_relative(archive_date),
            "payload_sha256": digest,
            "source_slots": list(payload["expected_slots"]),
            "counts": dict(payload["counts"]),
            "status": payload["status"],
            "authoritative": bool(payload["authoritative"]),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def publish(self, payload: Mapping[str, Any], *, mode: str) -> dict[str, Any]:
        archive_date = validate_research_archive(payload)
        normalized_mode = str(mode).upper()
        if normalized_mode not in _MODES:
            raise ValueError("research publication mode must be LIVE, REPLAY, or BACKFILL")
        relative = self._relative(archive_date)
        receipt_relative = self._receipt_relative(archive_date)
        digest = _sha256(payload)
        receipt = self._receipt(payload, digest)
        latest_updated = False
        with self._lock():
            manifest = self._manifest()
            existing = manifest.get(relative)
            if existing and existing != digest:
                raise ValueError("conflicting research archive re-import")
            if existing:
                if (
                    not self._path(relative).is_file()
                    or _sha256(self._read(relative)) != digest
                    or not self._path(receipt_relative).is_file()
                    or self._read(receipt_relative) != receipt
                ):
                    raise ValueError("research archive integrity mismatch")
            else:
                if self._path(relative).exists() or self._path(receipt_relative).exists():
                    raise ValueError("orphan research archive or receipt")
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

    def replace(
        self,
        payload: Mapping[str, Any],
        *,
        mode: str,
        expected_sha256: str,
        reason: str,
        source_provenance: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """CAS-replace one generic archive while preserving its preimage.

        Generic archive imports remain immutable through :meth:`publish`.
        Verified late recovery is the only caller of this separate path: the
        current manifest and payload must still match ``expected_sha256``
        before any canonical file or LIVE pointer is changed.  A replacement
        that already succeeded is a verified no-op, using its content-
        addressed history and supersession receipt as the proof of identity.
        """

        archive_date = validate_research_archive(payload)
        normalized_mode = str(mode).upper()
        if normalized_mode not in _MODES:
            raise ValueError(
                "research publication mode must be LIVE, REPLAY, or BACKFILL"
            )
        expected = str(expected_sha256 or "").strip().lower()
        if not _SHA256.fullmatch(expected):
            raise ValueError("research archive expected SHA must be SHA-256")
        normalized_reason = str(reason or "").strip()
        if not normalized_reason:
            raise ValueError("research archive replacement reason is required")
        if source_provenance is not None and not isinstance(
            source_provenance, Mapping
        ):
            raise ValueError("research archive source provenance is invalid")
        provenance = dict(source_provenance or {})
        try:
            json.dumps(provenance, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as error:
            raise ValueError("research archive source provenance is invalid") from error

        relative = self._relative(archive_date)
        receipt_relative = self._receipt_relative(archive_date)
        digest = _sha256(payload)
        replacement_receipt = self._receipt(payload, digest)
        history_relative = self._history_relative(archive_date, expected)
        history_receipt_relative = self._history_receipt_relative(
            archive_date, expected
        )
        supersession_relative = self._supersession_relative(archive_date, digest)

        def _result(
            *,
            replaced: bool,
            latest_updated: bool,
            manifest: Mapping[str, Any],
            include_preimage: bool = False,
            preimage_relative: str | None = None,
            preimage_receipt_relative: str | None = None,
        ) -> dict[str, Any]:
            result_preimage_relative = preimage_relative or history_relative
            result_preimage_receipt_relative = (
                preimage_receipt_relative or history_receipt_relative
            )
            return {
                "archive_date": archive_date,
                "mode": normalized_mode,
                "payload_path": relative,
                "receipt_path": receipt_relative,
                "payload_sha256": digest,
                "receipt_sha256": _sha256(replacement_receipt),
                "manifest_sha256": _sha256(manifest),
                "replaced": replaced,
                "previous_payload_path": (
                    result_preimage_relative if replaced or include_preimage else ""
                ),
                "previous_receipt_path": (
                    result_preimage_receipt_relative
                    if replaced or include_preimage
                    else ""
                ),
                "supersession_receipt_path": (
                    supersession_relative if replaced or include_preimage else ""
                ),
                "latest_updated": latest_updated,
                "reason": normalized_reason,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }

        def _restore_raw(path: Path, existed: bool, raw: bytes | None) -> None:
            if existed and raw is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            elif not existed:
                path.unlink(missing_ok=True)

        def _validate_existing_replacement(
            manifest: Mapping[str, Any],
        ) -> tuple[str, str]:
            payload_path = self._path(relative)
            receipt_path = self._path(receipt_relative)
            if (
                not payload_path.is_file()
                or not receipt_path.is_file()
                or manifest.get(relative) != digest
            ):
                raise ValueError("research archive replacement artifact is incomplete")
            current_payload = self._read(relative)
            if (
                _sha256(current_payload) != digest
                or validate_research_archive(current_payload) != archive_date
                or self._read(receipt_relative)
                != self._receipt(current_payload, digest)
            ):
                raise ValueError("research archive replacement integrity mismatch")
            supersession_path = self._path(supersession_relative)
            if not supersession_path.is_file():
                raise ValueError("research archive replacement evidence is incomplete")
            supersession = self._read(supersession_relative)
            if not isinstance(supersession, Mapping):
                raise ValueError("research archive replacement supersession is invalid")
            supersession_previous = str(
                supersession.get("previous_payload_sha256") or ""
            ).lower()
            if (
                not _SHA256.fullmatch(supersession_previous)
                or supersession_previous == digest
                or expected not in {supersession_previous, digest}
            ):
                raise ValueError("research archive replacement expected SHA mismatch")
            history_relative = self._history_relative(
                archive_date, supersession_previous
            )
            history_receipt_relative = self._history_receipt_relative(
                archive_date, supersession_previous
            )
            history_path = self._path(history_relative)
            history_receipt_path = self._path(history_receipt_relative)
            if not history_path.is_file() or not history_receipt_path.is_file():
                raise ValueError("research archive replacement evidence is incomplete")
            previous_payload = self._read(history_relative)
            previous_receipt = self._read(history_receipt_relative)
            if (
                _sha256(previous_payload) != supersession_previous
                or validate_research_archive(previous_payload) != archive_date
                or previous_receipt
                != self._receipt(previous_payload, supersession_previous)
            ):
                raise ValueError("research archive replacement history mismatch")
            previous_source = str(
                previous_payload.get("source_input_sha256") or ""
            ).lower()
            previous_manifest = dict(manifest)
            previous_manifest[relative] = supersession_previous
            latest_relative = "research/latest.json"
            latest_path = self._path(latest_relative)
            latest_current = None
            if latest_path.exists():
                if not latest_path.is_file():
                    raise ValueError("research archive latest pointer is invalid")
                latest_current = self._read(latest_relative)
                self._validate_pointer(latest_current)
            previous_latest = supersession.get("previous_latest_pointer")
            if previous_latest is not None:
                self._validate_pointer(previous_latest)
            previous_latest_sha = (
                _sha256(previous_latest) if previous_latest is not None else ""
            )
            expected_current_latest = self._latest_pointer(archive_date, digest)
            if normalized_mode == "LIVE":
                if latest_current != expected_current_latest:
                    raise ValueError(
                        "research archive replacement latest pointer mismatch"
                    )
                if previous_latest is not None and previous_latest != self._latest_pointer(
                    archive_date, supersession_previous
                ):
                    raise ValueError(
                        "research archive replacement previous latest pointer is not deterministic"
                    )
            elif latest_current != previous_latest:
                raise ValueError(
                    "research archive replacement previous latest pointer mismatch"
                )
            if (
                supersession.get("schema_version")
                != "v3_5.research_archive_supersession.v1"
                or supersession.get("archive_date") != archive_date
                or supersession.get("mode") != normalized_mode
                or supersession.get("payload_path") != relative
                or supersession.get("payload_sha256") != digest
                or (
                    "source_input_sha256" in supersession
                    and supersession.get("source_input_sha256")
                    != str(current_payload.get("source_input_sha256") or "")
                )
                or supersession.get("previous_payload_path") != history_relative
                or supersession.get("previous_payload_sha256")
                != supersession_previous
                or supersession.get("previous_receipt_path")
                != history_receipt_relative
                or supersession.get("previous_receipt_sha256")
                != _sha256(previous_receipt)
                or supersession.get("previous_source_input_sha256")
                != previous_source
                or supersession.get("reason") != normalized_reason
                or supersession.get("source_provenance") != provenance
                or supersession.get("previous_manifest_sha256")
                != _sha256(previous_manifest)
                or supersession.get("previous_latest_pointer_sha256")
                != previous_latest_sha
                or supersession.get("write_policy") != "read_only"
                or supersession.get("production_allowed") is not False
                or supersession.get("buy_gate_updated") is not False
                or supersession.get("orders_sent") is not False
            ):
                raise ValueError("research archive replacement supersession mismatch")
            return history_relative, history_receipt_relative

        with self._lock():
            manifest = self._manifest()
            current_digest = manifest.get(relative)
            payload_path = self._path(relative)
            receipt_path = self._path(receipt_relative)

            # A completed replacement can be retried with the original
            # expected preimage.  Validate every proof file before returning
            # the no-op so a damaged partial state cannot be accepted.
            if current_digest == digest:
                supersession_path = self._path(supersession_relative)
                if expected != digest or supersession_path.exists():
                    preimage_relative, preimage_receipt_relative = (
                        _validate_existing_replacement(manifest)
                    )
                    latest_updated = False
                    if normalized_mode == "LIVE":
                        latest_updated = self._update_latest(archive_date, digest)
                    return _result(
                        replaced=False,
                        latest_updated=latest_updated,
                        manifest=manifest,
                        include_preimage=True,
                        preimage_relative=preimage_relative,
                        preimage_receipt_relative=preimage_receipt_relative,
                    )
                if not payload_path.is_file() or not receipt_path.is_file():
                    raise ValueError("research archive replacement source is incomplete")
                current_payload = self._read(relative)
                if (
                    _sha256(current_payload) != digest
                    or validate_research_archive(current_payload) != archive_date
                    or self._read(receipt_relative)
                    != self._receipt(current_payload, digest)
                ):
                    raise ValueError("research archive replacement integrity mismatch")
                latest_updated = False
                if normalized_mode == "LIVE":
                    latest_updated = self._update_latest(archive_date, digest)
                return _result(
                    replaced=False,
                    latest_updated=latest_updated,
                    manifest=manifest,
                )

            # The compare-and-swap gate is deliberately before any history,
            # receipt, canonical, manifest, or latest-pointer write.
            if current_digest != expected:
                raise ValueError("research archive expected SHA mismatch")
            if not payload_path.is_file() or not receipt_path.is_file():
                raise ValueError("research archive replacement source is incomplete")

            previous_payload = self._read(relative)
            previous_receipt = self._read(receipt_relative)
            previous_digest = _sha256(previous_payload)
            if (
                previous_digest != expected
                or validate_research_archive(previous_payload) != archive_date
                or previous_receipt != self._receipt(previous_payload, expected)
            ):
                raise ValueError("research archive replacement integrity mismatch")
            if digest == previous_digest:
                latest_updated = False
                if normalized_mode == "LIVE":
                    latest_updated = self._update_latest(archive_date, digest)
                return _result(
                    replaced=False,
                    latest_updated=latest_updated,
                    manifest=manifest,
                )

            latest_relative = "research/latest.json"
            latest_path = self._path(latest_relative)
            latest_existed = latest_path.is_file()
            latest_raw = latest_path.read_bytes() if latest_existed else None
            latest_before = self._read(latest_relative) if latest_existed else None
            if latest_existed:
                self._validate_pointer(latest_before)

            history_path = self._path(history_relative)
            history_receipt_path = self._path(history_receipt_relative)
            if history_path.exists() and (
                not history_path.is_file()
                or self._read(history_relative) != previous_payload
            ):
                raise ValueError("research archive history conflict")
            if history_receipt_path.exists() and (
                not history_receipt_path.is_file()
                or self._read(history_receipt_relative) != previous_receipt
            ):
                raise ValueError("research archive history receipt conflict")
            supersession = {
                "schema_version": "v3_5.research_archive_supersession.v1",
                "archive_date": archive_date,
                "mode": normalized_mode,
                "payload_path": relative,
                "payload_sha256": digest,
                "source_input_sha256": str(payload.get("source_input_sha256") or ""),
                "previous_payload_path": history_relative,
                "previous_payload_sha256": previous_digest,
                "previous_receipt_path": history_receipt_relative,
                "previous_receipt_sha256": _sha256(previous_receipt),
                "previous_source_input_sha256": str(
                    previous_payload.get("source_input_sha256") or ""
                ),
                "reason": normalized_reason,
                "source_provenance": provenance,
                "previous_manifest_sha256": _sha256(manifest),
                "previous_latest_pointer": latest_before,
                "previous_latest_pointer_sha256": (
                    _sha256(latest_before) if latest_before is not None else ""
                ),
                "write_policy": "read_only",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
            supersession_path = self._path(supersession_relative)
            if supersession_path.exists() and (
                not supersession_path.is_file()
                or self._read(supersession_relative) != supersession
            ):
                raise ValueError("research archive supersession conflict")

            manifest_path = self._path("manifest.json")
            manifest_existed = manifest_path.is_file()
            manifest_raw = manifest_path.read_bytes() if manifest_existed else None
            payload_raw = payload_path.read_bytes()
            receipt_raw = receipt_path.read_bytes()
            latest_updated = False
            try:
                if not history_path.exists():
                    self._write(history_relative, previous_payload)
                if not history_receipt_path.exists():
                    self._write(history_receipt_relative, previous_receipt)
                if not supersession_path.exists():
                    self._write(supersession_relative, supersession)
                self._write(relative, payload)
                self._write(receipt_relative, replacement_receipt)
                manifest[relative] = digest
                self._write_manifest(manifest)
                if normalized_mode == "LIVE":
                    latest_updated = self._update_latest(archive_date, digest)
            except Exception:
                # Preserve the old preimage/history as evidence, while
                # restoring every canonical view if a later write fails.
                _restore_raw(payload_path, True, payload_raw)
                _restore_raw(receipt_path, True, receipt_raw)
                _restore_raw(manifest_path, manifest_existed, manifest_raw)
                _restore_raw(latest_path, latest_existed, latest_raw)
                raise

        return _result(
            replaced=True,
            latest_updated=latest_updated,
            manifest=manifest,
        )

    def _update_latest(self, archive_date: str, digest: str) -> bool:
        relative = "research/latest.json"
        destination = self._path(relative)
        if destination.is_file():
            existing = self._read(relative)
            self._validate_pointer(existing)
            if str(existing["archive_date"]) > archive_date:
                raise ValueError("LIVE research publication cannot move latest backwards")
            if str(existing["archive_date"]) == archive_date and existing["payload_sha256"] == digest:
                return False
        body = {
            "schema_version": "v3_5.research_latest_pointer.v1",
            "archive_date": archive_date,
            "payload_path": self._relative(archive_date),
            "payload_sha256": digest,
        }
        pointer = {**body, "pointer_semantic_hash": _sha256(body)}
        self._write(relative, pointer)
        return True

    @staticmethod
    def _latest_pointer(archive_date: str, digest: str) -> dict[str, Any]:
        body = {
            "schema_version": "v3_5.research_latest_pointer.v1",
            "archive_date": archive_date,
            "payload_path": ResearchArchiveStore._relative(archive_date),
            "payload_sha256": digest,
        }
        return {**body, "pointer_semantic_hash": _sha256(body)}

    @staticmethod
    def _validate_pointer(pointer: Mapping[str, Any]) -> None:
        if not isinstance(pointer, Mapping) or set(pointer) != {
            "schema_version",
            "archive_date",
            "payload_path",
            "payload_sha256",
            "pointer_semantic_hash",
        }:
            raise ValueError("invalid research latest pointer")
        archive_date = _date(str(pointer.get("archive_date") or ""))
        body = {key: value for key, value in pointer.items() if key != "pointer_semantic_hash"}
        if (
            pointer.get("schema_version") != "v3_5.research_latest_pointer.v1"
            or pointer.get("payload_path") != ResearchArchiveStore._relative(archive_date)
            or not _SHA256.fullmatch(str(pointer.get("payload_sha256") or ""))
            or pointer.get("pointer_semantic_hash") != _sha256(body)
        ):
            raise ValueError("invalid research latest pointer")

    def read_exact(self, archive_date: str) -> dict[str, Any] | None:
        archive_date = _date(archive_date)
        relative = self._relative(archive_date)
        receipt_relative = self._receipt_relative(archive_date)
        payload_path = self._path(relative)
        receipt_path = self._path(receipt_relative)
        manifest = self._manifest()
        if not payload_path.is_file():
            if payload_path.exists() or receipt_path.exists() or relative in manifest:
                raise ValueError("research archive manifest or receipt mismatch")
            return None
        payload = self._read(relative)
        if payload.get("schema_version") == PRODUCT_SCHEMA_VERSION:
            raise ValueError("generic research archive path contains a day product")
        digest = _sha256(payload)
        if (
            manifest.get(relative) != digest
            or not receipt_path.is_file()
            or self._read(receipt_relative) != self._receipt(payload, digest)
            or validate_research_archive(payload) != archive_date
        ):
            raise ValueError("research archive manifest or receipt mismatch")
        return payload

    def publish_day_product(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Publish a complete exact-date day product in its own namespace.

        The legacy generic archive and its receipt remain authoritative at
        ``research/archives/{date}.json``.  Day products use a separate
        manifest key and pointer namespace, so publishing a full-day product
        cannot overwrite or reinterpret a same-date generic archive.
        """

        archive_date = validate_research_day_product(payload)
        relative = self._day_relative(archive_date)
        receipt_relative = self._day_receipt_relative(archive_date)
        digest = _sha256(payload)
        receipt = self._day_receipt(payload, digest)
        latest_updated = False
        current_updated = False
        with self._lock():
            manifest = self._manifest()
            existing = manifest.get(relative)
            payload_path = self._path(relative)
            receipt_path = self._path(receipt_relative)
            if existing and existing != digest:
                raise ValueError("conflicting research day product re-import")
            if existing:
                existing_payload = self._read(relative) if payload_path.is_file() else {}
                if existing_payload.get("schema_version") != PRODUCT_SCHEMA_VERSION:
                    raise ValueError("existing generic archive blocks day product")
                if (
                    not payload_path.is_file()
                    or _sha256(existing_payload) != digest
                    or not receipt_path.is_file()
                    or self._read(receipt_relative) != receipt
                ):
                    raise ValueError("research day product manifest or receipt mismatch")
            else:
                if payload_path.exists() or receipt_path.exists():
                    raise ValueError("orphan research archive or receipt")
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
            "receipt_sha256": _sha256(receipt),
            "manifest_sha256": _sha256(self._manifest()),
            "latest_updated": latest_updated,
            "current_updated": current_updated,
            "current_path": current_relative,
            "current_sha256": _sha256(current),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def _update_day_latest(self, archive_date: str, digest: str) -> bool:
        relative = self._day_latest_relative()
        destination = self._path(relative)
        if destination.is_file():
            existing = self._read(relative)
            self._validate_day_latest_pointer(existing)
            existing_position = str(existing["archive_date"])
            if existing_position > archive_date:
                raise ValueError("research day product cannot move latest backwards")
            if (
                existing_position == archive_date
                and existing["payload_sha256"] == digest
            ):
                return False
        elif destination.exists():
            raise ValueError("invalid research latest pointer")
        body = {
            "schema_version": "v3_5.research_day_latest_pointer.v1",
            "archive_date": archive_date,
            "payload_path": self._day_relative(archive_date),
            "payload_sha256": digest,
        }
        self._write(relative, {**body, "pointer_semantic_hash": _sha256(body)})
        return True

    @staticmethod
    def _validate_day_latest_pointer(pointer: Mapping[str, Any]) -> None:
        fields = {
            "schema_version",
            "archive_date",
            "payload_path",
            "payload_sha256",
            "pointer_semantic_hash",
        }
        if not isinstance(pointer, Mapping) or set(pointer) != fields:
            raise ValueError("invalid research day latest pointer")
        archive_date = _date(str(pointer.get("archive_date") or ""))
        body = {
            key: value for key, value in pointer.items() if key != "pointer_semantic_hash"
        }
        if (
            pointer.get("schema_version") != "v3_5.research_day_latest_pointer.v1"
            or pointer.get("payload_path") != ResearchArchiveStore._day_relative(archive_date)
            or not _SHA256.fullmatch(str(pointer.get("payload_sha256") or ""))
            or pointer.get("pointer_semantic_hash") != _sha256(body)
        ):
            raise ValueError("invalid research day latest pointer")

    def _update_day_current(self, archive_date: str, digest: str) -> bool:
        relative = self._day_current_relative()
        destination = self._path(relative)
        if destination.is_file():
            existing = self._read(relative)
            self._validate_current_pointer(existing)
            existing_position = str(existing["archive_date"])
            if existing_position > archive_date:
                raise ValueError("research day product cannot move current backwards")
            if (
                existing_position == archive_date
                and existing["payload_sha256"] == digest
            ):
                return False
        elif destination.exists():
            raise ValueError("invalid research current pointer")
        body = {
            "schema_version": "v3_5.research_day_current_pointer.v1",
            "archive_date": archive_date,
            "payload_path": self._day_relative(archive_date),
            "payload_sha256": digest,
        }
        self._write(relative, {**body, "pointer_semantic_hash": _sha256(body)})
        return True

    @staticmethod
    def _validate_current_pointer(pointer: Mapping[str, Any]) -> None:
        fields = {
            "schema_version",
            "archive_date",
            "payload_path",
            "payload_sha256",
            "pointer_semantic_hash",
        }
        if not isinstance(pointer, Mapping) or set(pointer) != fields:
            raise ValueError("invalid research current pointer")
        archive_date = _date(str(pointer.get("archive_date") or ""))
        body = {
            key: value for key, value in pointer.items() if key != "pointer_semantic_hash"
        }
        if (
            pointer.get("schema_version") != "v3_5.research_day_current_pointer.v1"
            or pointer.get("payload_path") != ResearchArchiveStore._day_relative(archive_date)
            or not _SHA256.fullmatch(str(pointer.get("payload_sha256") or ""))
            or pointer.get("pointer_semantic_hash") != _sha256(body)
        ):
            raise ValueError("invalid research current pointer")

    def read_day_exact(self, archive_date: str) -> dict[str, Any] | None:
        archive_date = _date(archive_date)
        relative = self._day_relative(archive_date)
        receipt_relative = self._day_receipt_relative(archive_date)
        payload_path = self._path(relative)
        receipt_path = self._path(receipt_relative)
        manifest = self._manifest()
        if not payload_path.is_file():
            if payload_path.exists() or receipt_path.exists() or relative in manifest:
                raise ValueError("research day product manifest or receipt mismatch")
            return None
        payload = self._read(relative)
        if payload.get("schema_version") != PRODUCT_SCHEMA_VERSION:
            return None
        digest = _sha256(payload)
        receipt = self._day_receipt(payload, digest)
        if (
            manifest.get(relative) != digest
            or not receipt_path.is_file()
            or self._read(receipt_relative) != receipt
            or validate_research_day_product(payload) != archive_date
        ):
            raise ValueError("research day product manifest or receipt mismatch")
        return payload

    def read_day_latest(self) -> dict[str, Any] | None:
        relative = self._day_latest_relative()
        pointer_path = self._path(relative)
        if not pointer_path.is_file():
            if pointer_path.exists():
                raise ValueError("invalid research latest pointer")
            return None
        pointer = self._read(relative)
        self._validate_day_latest_pointer(pointer)
        payload = self.read_day_exact(str(pointer["archive_date"]))
        if payload is None or _sha256(payload) != pointer["payload_sha256"]:
            return None
        return payload

    def read_day_current(self) -> dict[str, Any] | None:
        relative = self._day_current_relative()
        pointer_path = self._path(relative)
        if not pointer_path.is_file():
            if pointer_path.exists():
                raise ValueError("invalid research current pointer")
            return None
        pointer = self._read(relative)
        self._validate_current_pointer(pointer)
        payload = self.read_day_exact(str(pointer["archive_date"]))
        if payload is None or _sha256(payload) != pointer["payload_sha256"]:
            raise ValueError("research current pointer target mismatch")
        return payload

    def read_latest(self) -> dict[str, Any] | None:
        relative = "research/latest.json"
        pointer_path = self._path(relative)
        if not pointer_path.is_file():
            if pointer_path.exists():
                raise ValueError("invalid research latest pointer")
            return None
        pointer = self._read(relative)
        self._validate_pointer(pointer)
        payload = self.read_exact(str(pointer["archive_date"]))
        if payload is None or _sha256(payload) != pointer["payload_sha256"]:
            raise ValueError("research latest pointer target mismatch")
        return payload

    def list_dates(self) -> list[str]:
        dates = []
        for relative in self._manifest():
            match = re.fullmatch(
                r"research/archives/(\d{8})\.json",
                relative,
            )
            if match:
                dates.append(match.group(1))
        return sorted(set(dates), reverse=True)

class ResearchSelectionStore(NativeDataStore):
    """Append-only selection ledger under its own research namespace."""

    _MANIFEST_RELATIVE = "research/selection/manifest.json"
    _CURRENT_RELATIVE = "research/selection/current.json"
    _SELECTION_ROOT = "research/selection"
    _RECEIPT_ROOT = "receipts/research/selection"
    _RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

    def _path(self, relative: str) -> Path:
        return resolve_owned_path(self.root, relative)

    @classmethod
    def _artifact_relative(cls, target_trade_date: str, run_id: str) -> str:
        return f"{cls._SELECTION_ROOT}/{target_trade_date}/{run_id}.json"

    @classmethod
    def _receipt_relative(cls, target_trade_date: str, run_id: str) -> str:
        return f"{cls._RECEIPT_ROOT}/{target_trade_date}/{run_id}.json"

    @classmethod
    def _run_manifest_relative(cls, target_trade_date: str, run_id: str) -> str:
        return f"{cls._SELECTION_ROOT}/{target_trade_date}/{run_id}.manifest.json"

    @classmethod
    def _date_current_relative(cls, target_trade_date: str) -> str:
        return f"{cls._SELECTION_ROOT}/{target_trade_date}/current.json"

    @staticmethod
    def _raw_sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _canonical_sha(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @classmethod
    def _empty_manifest(cls) -> dict[str, Any]:
        return {
            "schema_version": "v3_5.selection_manifest.v1",
            "namespace": cls._SELECTION_ROOT,
            "entries": {},
        }

    @classmethod
    def _validate_manifest(cls, value: Mapping[str, Any]) -> None:
        if not isinstance(value, Mapping) or set(value) != {
            "schema_version",
            "namespace",
            "entries",
        }:
            raise ValueError("invalid selection manifest")
        if value.get("schema_version") != "v3_5.selection_manifest.v1" or value.get("namespace") != cls._SELECTION_ROOT:
            raise ValueError("invalid selection manifest namespace")
        entries = value.get("entries")
        if not isinstance(entries, Mapping):
            raise ValueError("invalid selection manifest entries")
        for relative, digest in entries.items():
            if not isinstance(relative, str) or not (
                relative.startswith(f"{cls._SELECTION_ROOT}/")
                or relative.startswith(f"{cls._RECEIPT_ROOT}/")
            ):
                raise ValueError("selection manifest path escapes namespace")
            if not _SHA256.fullmatch(str(digest or "")):
                raise ValueError("invalid selection manifest SHA")

    def _manifest(self) -> dict[str, Any]:
        path = self._path(self._MANIFEST_RELATIVE)
        if not path.exists():
            return self._empty_manifest()
        value = self._read(self._MANIFEST_RELATIVE)
        self._validate_manifest(value)
        return value

    def _write_manifest(self, value: Mapping[str, Any]) -> None:
        self._validate_manifest(value)
        self._write(self._MANIFEST_RELATIVE, dict(value))

    @contextmanager
    def _lock(self):
        """Use a selection-local lock; never create NativeDataStore's root lock."""

        path = self._path(f"{self._SELECTION_ROOT}/.import.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + 10
        token = f"{os.getpid()}:{uuid4().hex}"
        while True:
            try:
                handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(handle, token.encode("ascii"))
                os.close(handle)
                break
            except FileExistsError:
                try:
                    if time.time() - path.stat().st_mtime > 30:
                        path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise ValueError("selection import lock timeout")
                time.sleep(0.02)
        try:
            yield
        finally:
            try:
                if path.read_text(encoding="ascii") == token:
                    path.unlink()
            except FileNotFoundError:
                pass

    @classmethod
    def _receipt(cls, payload: Mapping[str, Any], artifact_relative: str, artifact_sha: str) -> dict[str, Any]:
        return {
            "schema_version": "v3_5.selection_receipt.v1",
            "contract_id": SELECTION_CONTRACT_ID,
            "target_trade_date": payload["target_trade_date"],
            "source_date": payload["source_date"],
            "run_id": payload["run_id"],
            "origin": payload["origin"],
            "payload_path": artifact_relative,
            "payload_sha256": artifact_sha,
            "status": payload["status"],
            "counts": dict(payload["counts"]),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    @classmethod
    def _current_pointer(
        cls,
        payload: Mapping[str, Any],
        *,
        artifact_relative: str,
        artifact_sha: str,
        receipt_relative: str,
        receipt_sha: str,
        manifest_relative: str,
        manifest_sha: str,
    ) -> dict[str, Any]:
        body = {
            "schema_version": "v3_5.selection_current_pointer.v1",
            "namespace": cls._SELECTION_ROOT,
            "target_trade_date": payload["target_trade_date"],
            "run_id": payload["run_id"],
            "generated_at": payload["generated_at"],
            "artifact_path": artifact_relative,
            "artifact_sha256": artifact_sha,
            "receipt_path": receipt_relative,
            "receipt_sha256": receipt_sha,
            "manifest_path": manifest_relative,
            "manifest_sha256": manifest_sha,
        }
        return {**body, "pointer_semantic_hash": cls._canonical_sha(body)}

    @classmethod
    def _validate_current(
        cls,
        value: Mapping[str, Any],
        *,
        target_trade_date: str | None = None,
    ) -> None:
        fields = {
            "schema_version",
            "namespace",
            "target_trade_date",
            "run_id",
            "generated_at",
            "artifact_path",
            "artifact_sha256",
            "receipt_path",
            "receipt_sha256",
            "manifest_path",
            "manifest_sha256",
            "pointer_semantic_hash",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("invalid selection current pointer")
        selected = _date(str(value.get("target_trade_date") or ""))
        if target_trade_date is not None and selected != target_trade_date:
            raise ValueError("selection current target date mismatch")
        run_id = value.get("run_id")
        if not isinstance(run_id, str) or not cls._RUN_ID.fullmatch(run_id):
            raise ValueError("invalid selection current run_id")
        if value.get("schema_version") != "v3_5.selection_current_pointer.v1" or value.get("namespace") != cls._SELECTION_ROOT:
            raise ValueError("invalid selection current namespace")
        if value.get("artifact_path") != cls._artifact_relative(selected, run_id) or value.get("receipt_path") != cls._receipt_relative(selected, run_id):
            raise ValueError("invalid selection current paths")
        if value.get("manifest_path") != cls._run_manifest_relative(selected, run_id):
            raise ValueError("invalid selection current manifest path")
        for field in ("artifact_sha256", "receipt_sha256", "manifest_sha256"):
            if not _SHA256.fullmatch(str(value.get(field) or "")):
                raise ValueError("invalid selection current SHA")
        body = {key: item for key, item in value.items() if key != "pointer_semantic_hash"}
        if value.get("pointer_semantic_hash") != cls._canonical_sha(body):
            raise ValueError("invalid selection current semantic hash")

    @classmethod
    def _global_current_pointer(cls, date_current: Mapping[str, Any]) -> dict[str, Any]:
        body = {
            "schema_version": "v3_5.selection_global_current.v1",
            "namespace": cls._SELECTION_ROOT,
            "target_trade_date": date_current["target_trade_date"],
            "current_path": f"{cls._SELECTION_ROOT}/{date_current['target_trade_date']}/current.json",
            "run_id": date_current["run_id"],
            "artifact_sha256": date_current["artifact_sha256"],
        }
        return {**body, "pointer_semantic_hash": cls._canonical_sha(body)}

    @classmethod
    def _validate_global_current(cls, value: Mapping[str, Any]) -> None:
        fields = {
            "schema_version",
            "namespace",
            "target_trade_date",
            "current_path",
            "run_id",
            "artifact_sha256",
            "pointer_semantic_hash",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("invalid selection global current pointer")
        target = _date(str(value.get("target_trade_date") or ""))
        run_id = value.get("run_id")
        if not isinstance(run_id, str) or not cls._RUN_ID.fullmatch(run_id):
            raise ValueError("invalid selection global current run_id")
        if value.get("schema_version") != "v3_5.selection_global_current.v1" or value.get("namespace") != cls._SELECTION_ROOT:
            raise ValueError("invalid selection global current namespace")
        if value.get("current_path") != f"{cls._SELECTION_ROOT}/{target}/current.json" or not _SHA256.fullmatch(str(value.get("artifact_sha256") or "")):
            raise ValueError("invalid selection global current target")
        body = {key: item for key, item in value.items() if key != "pointer_semantic_hash"}
        if value.get("pointer_semantic_hash") != cls._canonical_sha(body):
            raise ValueError("invalid selection global current semantic hash")

    @staticmethod
    def _pointer_value(document: Any, pointer: str) -> Any:
        if pointer == "":
            return document
        if not isinstance(pointer, str) or not pointer.startswith("/"):
            raise ValueError("invalid selection source JSON pointer")
        current = document
        for raw_part in pointer[1:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, list):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError) as error:
                    raise ValueError("selection source JSON pointer missing") from error
            elif isinstance(current, Mapping) and part in current:
                current = current[part]
            else:
                raise ValueError("selection source JSON pointer missing")
        return current

    @classmethod
    def _verify_source_ref(
        cls,
        ref: Mapping[str, Any],
        *,
        expected_target_trade_date: str | None = None,
    ) -> dict[str, Any]:
        path_value = ref.get("path")
        if not isinstance(path_value, str) or not path_value:
            raise ValueError("selection source path is missing")
        path = Path(path_value)
        if not path.is_file() or path.is_symlink():
            raise ValueError("selection source file is unavailable")
        raw = path.read_bytes()
        raw_sha = hashlib.sha256(raw).hexdigest()
        if raw_sha != str(ref.get("raw_sha256") or "").lower():
            raise ValueError("selection source raw SHA mismatch")
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("selection source JSON is invalid") from error
        if ref.get("type") == RESEARCH_SUPPLY_TYPE:
            validate_research_supply_envelope(
                document,
                expected_target_trade_date=expected_target_trade_date,
            )
            pointer = ref.get("json_pointer")
            if not isinstance(pointer, str) or not re.fullmatch(
                r"/frozen_payload/event_cards/(?:0|[1-9][0-9]*)", pointer
            ):
                raise ValueError("research supply source JSON pointer must target event card")
            selected = cls._pointer_value(document, pointer)
            if not isinstance(selected, Mapping):
                raise ValueError("research supply selected card is invalid")
            if ref.get("source_date") != document.get("source_date"):
                raise ValueError("research supply source date mismatch")
            if (
                expected_target_trade_date is not None
                and document.get("target_trade_date") != expected_target_trade_date
            ):
                raise ValueError("research supply target date mismatch")
            if ref.get("frozen_payload_sha256") != document.get("frozen_payload_sha256"):
                raise ValueError("research supply frozen SHA mismatch")
            source_time = ref.get("source_time")
            if source_time != document.get("generated_at"):
                raise ValueError("research supply source_time does not match envelope")
            receipt_path_value = ref.get("supply_receipt_path")
            if not isinstance(receipt_path_value, str) or not receipt_path_value:
                raise ValueError("research supply receipt path is missing")
            receipt_path = Path(receipt_path_value)
            if not receipt_path.is_file() or receipt_path.is_symlink():
                raise ValueError("research supply receipt is unavailable")
            receipt_raw = receipt_path.read_bytes()
            receipt_sha = hashlib.sha256(receipt_raw).hexdigest()
            if receipt_sha != str(ref.get("supply_receipt_sha256") or "").lower():
                raise ValueError("research supply receipt SHA mismatch")
            try:
                receipt = json.loads(receipt_raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("research supply receipt is invalid JSON") from error
            validate_research_supply_receipt(
                receipt,
                envelope=document,
                artifact_path=str(path),
                artifact_sha256=raw_sha,
            )
            return {
                "card": selected,
                "document": document,
                "supply_receipt": receipt,
                "kind": RESEARCH_SUPPLY_TYPE,
            }
        pointer = str(ref.get("json_pointer") or "")
        if not re.fullmatch(
            r"/frozen_payload/event_cards/(?:0|[1-9][0-9]*)", pointer
        ):
            raise ValueError("selection source JSON pointer must target frozen event card")
        selected = cls._pointer_value(document, pointer)
        frozen_payload = cls._pointer_value(document, "/frozen_payload")
        if not isinstance(selected, Mapping) or not selected.get("event_id") or not isinstance(selected.get("entities"), list):
            raise ValueError("selection source selected card is invalid")
        frozen = hashlib.sha256(
            json.dumps(
                frozen_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if frozen != str(ref.get("frozen_payload_sha256") or "").lower():
            raise ValueError("selection source frozen SHA mismatch")
        source_date = str(ref.get("source_date") or "")
        document_source_date = document.get("source_date")
        if document_source_date is None and isinstance(frozen_payload, Mapping):
            document_source_date = frozen_payload.get("source_date")
        if document_source_date is None or str(document_source_date) != source_date:
            raise ValueError("selection source date mismatch")
        document_target_date = document.get("target_trade_date")
        if document_target_date is None and isinstance(frozen_payload, Mapping):
            document_target_date = frozen_payload.get("target_trade_date")
        if document_target_date is None:
            raise ValueError("selection source target date is missing")
        if (
            expected_target_trade_date is not None
            and str(document_target_date) != expected_target_trade_date
        ):
            raise ValueError("selection source target date mismatch")
        document_generated_at = document.get("generated_at")
        if document_generated_at is None:
            raise ValueError("selection source generated_at is missing")
        try:
            expected_time = datetime.fromisoformat(
                str(ref.get("source_time") or "").replace("Z", "+00:00")
            )
            actual_time = datetime.fromisoformat(
                str(document_generated_at).replace("Z", "+00:00")
            )
        except ValueError as error:
            raise ValueError("selection source generated_at is invalid") from error
        if (
            expected_time.tzinfo is None
            or expected_time.utcoffset() is None
            or actual_time.tzinfo is None
            or actual_time.utcoffset() is None
            or expected_time.astimezone(_SHANGHAI)
            != actual_time.astimezone(_SHANGHAI)
        ):
            raise ValueError("selection source_time does not match source envelope")
        return {"card": selected, "document": document}

    @staticmethod
    def _selection_identity_text(value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def _source_ref_identity(cls, ref: Mapping[str, Any]) -> tuple[str, ...]:
        """Return immutable locator fields used by formal proof bindings."""

        return tuple(
            cls._selection_identity_text(ref.get(field))
            for field in (
                "path",
                "raw_sha256",
                "frozen_payload_sha256",
                "json_pointer",
                "source_date",
                "source_time",
            )
        )

    @classmethod
    def _verify_candidate_source_projection(
        cls,
        candidate: Mapping[str, Any],
        ref: Mapping[str, Any],
        verified: Mapping[str, Any],
        *,
        source_date: str,
        target_trade_date: str,
        cutoff_at: str | None = None,
    ) -> None:
        card = verified.get("card")
        if not isinstance(card, Mapping):
            raise ValueError("selection candidate source card is missing")
        document = verified.get("document")
        if not isinstance(document, Mapping):
            raise ValueError("selection candidate source envelope is missing")
        if ref.get("source_date") != source_date:
            raise ValueError("selection candidate source date binding mismatch")
        if ref.get("type") == RESEARCH_SUPPLY_TYPE:
            if document.get("target_trade_date") != target_trade_date:
                raise ValueError("selection candidate target date mismatch")
            frozen_payload = document.get("frozen_payload")
            if not isinstance(frozen_payload, Mapping):
                raise ValueError("research supply frozen payload is missing")
            ticker = cls._selection_identity_text(card.get("ticker"))
            if not re.fullmatch(r"\d{5}\.HK", ticker):
                raise ValueError("research supply card ticker is invalid")
            event_id = cls._selection_identity_text(card.get("event_id"))
            if event_id != candidate.get("event_id"):
                raise ValueError("selection candidate source identity mismatch")
            candidate_entity = cls._selection_identity_text(candidate.get("entity_id"))
            if candidate_entity != ticker:
                raise ValueError("selection candidate source entity mismatch")
            code, market = ticker.rsplit(".", 1)
            expected_candidate_id = f"{market}.{code}|{ticker}"
            if candidate.get("candidate_id") != expected_candidate_id:
                raise ValueError("selection candidate identity mismatch")
            if candidate.get("market") != market or candidate.get("normalized_code") != code:
                raise ValueError("selection candidate normalized identity mismatch")
            if candidate.get("event_stock_link_id") != f"{event_id}|{expected_candidate_id}":
                raise ValueError("selection candidate event link mismatch")

            def supply_text(value: Any) -> str:
                if value is None:
                    return ""
                if isinstance(value, str):
                    return value.strip()
                if isinstance(value, (Mapping, list)):
                    return json.dumps(
                        value,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                return str(value).strip()

            for field in (
                "bucket",
                "catalyst",
                "counterevidence",
                "invalidation",
                "evidence_level",
                "financial_bridge",
                "consensus",
                "overnight_pending",
            ):
                if candidate.get(field) != supply_text(card.get(field)):
                    raise ValueError(f"selection candidate source {field} mismatch")
            if candidate.get("source_metadata") != {"supply_card": dict(card)}:
                raise ValueError("selection candidate source metadata mismatch")
            route_status = frozen_payload.get("route_status")
            if not isinstance(route_status, Mapping) or candidate.get("route_status") != {
                "R1": route_status.get("R1"),
                "R6": route_status.get("R6"),
            }:
                raise ValueError("selection candidate route status mismatch")
            official = card.get("official_source")
            if not isinstance(official, Mapping):
                raise ValueError("research supply official source is missing")
            expected_status = cls._selection_identity_text(official.get("identity_status"))
            if not expected_status or expected_status.upper() in {
                "UNKNOWN",
                "UNVERIFIED",
                "CANNOT_CONFIRM",
                "NOT_MATERIALIZED",
            }:
                expected_status = "UNVERIFIED"
            if candidate.get("source_status") != expected_status:
                raise ValueError("selection candidate source status mismatch")
            eligibility = card.get("eligibility_status")
            if isinstance(eligibility, Mapping):
                expected_eligibility = cls._selection_identity_text(eligibility.get("status"))
            elif isinstance(eligibility, str) and eligibility.strip():
                expected_eligibility = eligibility.strip()
            else:
                expected_eligibility = ""
            if expected_eligibility not in {"ELIGIBILITY_CANNOT_CONFIRM", "ELIGIBLE"}:
                expected_eligibility = "ELIGIBILITY_CANNOT_CONFIRM"
            if candidate.get("eligibility") != expected_eligibility:
                raise ValueError("selection candidate source eligibility mismatch")
            published_value = card.get("published_at")
            if published_value is None:
                published_value = official.get("published_at")
            expected_published_at = supply_text(published_value)
            if candidate.get("published_at") != expected_published_at:
                raise ValueError("selection candidate published_at mismatch")
            expected_aware = _selection_aware_hkt(expected_published_at)
            if candidate.get("published_at_aware") != expected_aware:
                raise ValueError("selection candidate published_at projection mismatch")
            if candidate.get("source_time") != ref.get("source_time"):
                raise ValueError("selection candidate source_time mismatch")
            if cutoff_at is None:
                cutoff_at = str(document.get("cutoff_at") or "")
            try:
                cutoff = datetime.fromisoformat(str(cutoff_at).replace("Z", "+00:00"))
                published = (
                    datetime.fromisoformat(expected_aware.replace("Z", "+00:00"))
                    if expected_aware
                    else None
                )
            except ValueError as error:
                raise ValueError("selection candidate cutoff or published timestamp is invalid") from error
            expected_pit = (
                "CANNOT_CONFIRM"
                if cutoff.tzinfo is None or cutoff.utcoffset() is None or published is None
                else "READY"
                if published.astimezone(_SHANGHAI) <= cutoff.astimezone(_SHANGHAI)
                else "PIT_FAILED"
            )
            if candidate.get("pit_status") != expected_pit:
                raise ValueError("selection candidate PIT status mismatch")
            if candidate.get("acceptance") != "RESEARCH_SUPPLY_ONLY":
                raise ValueError("selection candidate supply acceptance mismatch")
            return
        raw_target_date = document.get("target_trade_date")
        frozen_payload = document.get("frozen_payload")
        if raw_target_date is None and isinstance(frozen_payload, Mapping):
            raw_target_date = frozen_payload.get("target_trade_date")
        if str(raw_target_date) != target_trade_date:
            raise ValueError("selection candidate target date mismatch")
        event_id = cls._selection_identity_text(card.get("event_id"))
        if event_id != candidate.get("event_id"):
            raise ValueError("selection candidate source identity mismatch")
        entities = card.get("entities")
        if not isinstance(entities, list) or len(entities) != 1:
            raise ValueError("selection candidate source entities are ambiguous")
        source_entity = cls._selection_identity_text(entities[0])
        candidate_entity = cls._selection_identity_text(candidate.get("entity_id"))
        if source_entity != candidate_entity:
            raise ValueError("selection candidate source entity mismatch")
        if "." not in candidate_entity:
            raise ValueError("selection candidate entity identity is invalid")
        source_code, source_market = candidate_entity.rsplit(".", 1)
        if (
            source_code.strip().upper() != cls._selection_identity_text(candidate.get("normalized_code")).upper()
            or source_market.strip().upper() != cls._selection_identity_text(candidate.get("market")).upper()
        ):
            raise ValueError("selection candidate normalized identity mismatch")
        expected_candidate_id = (
            f"{cls._selection_identity_text(candidate.get('market')).upper()}."
            f"{cls._selection_identity_text(candidate.get('normalized_code')).upper()}|"
            f"{candidate_entity}"
        )
        if candidate.get("candidate_id") != expected_candidate_id:
            raise ValueError("selection candidate identity mismatch")
        if candidate.get("event_stock_link_id") != f"{event_id}|{expected_candidate_id}":
            raise ValueError("selection candidate event link mismatch")

        source = card.get("source") if isinstance(card.get("source"), Mapping) else {}
        for field in (
            "bucket",
            "catalyst",
            "counterevidence",
            "invalidation",
            "evidence_level",
            "financial_bridge",
            "consensus",
            "overnight_pending",
        ):
            expected = cls._selection_identity_text(card.get(field))
            if candidate.get(field) != expected:
                raise ValueError(f"selection candidate source {field} mismatch")
        expected_metadata = dict(source)
        if candidate.get("source_metadata") != expected_metadata:
            raise ValueError("selection candidate source metadata mismatch")
        expected_status = cls._selection_identity_text(source.get("status")) or "UNVERIFIED"
        if candidate.get("source_status") != expected_status:
            raise ValueError("selection candidate source status mismatch")
        raw_eligibility = card.get("eligibility")
        if isinstance(raw_eligibility, Mapping):
            expected_eligibility = (
                cls._selection_identity_text(raw_eligibility.get("status"))
                or "ELIGIBILITY_CANNOT_CONFIRM"
            )
        elif isinstance(raw_eligibility, str) and raw_eligibility.strip():
            expected_eligibility = raw_eligibility.strip()
        else:
            expected_eligibility = "ELIGIBILITY_CANNOT_CONFIRM"
        if candidate.get("eligibility") != expected_eligibility:
            raise ValueError("selection candidate source eligibility mismatch")
        expected_published_at = cls._selection_identity_text(source.get("published_at"))
        if candidate.get("published_at") != expected_published_at:
            raise ValueError("selection candidate published_at mismatch")
        if candidate.get("published_at_aware") != _selection_aware_hkt(expected_published_at):
            raise ValueError("selection candidate published_at projection mismatch")
        if candidate.get("source_time") != ref.get("source_time"):
            raise ValueError("selection candidate source_time mismatch")
        try:
            source_time = datetime.fromisoformat(
                str(ref.get("source_time") or "").replace("Z", "+00:00")
            )
        except ValueError as error:
            raise ValueError("selection candidate source_time is invalid") from error
        if source_time.tzinfo is None or source_time.utcoffset() is None:
            raise ValueError("selection candidate source_time must include timezone")
        for field in ("official_url", "published_at", "source_status"):
            if field in ref:
                expected = {
                    "official_url": source.get("official_url", ""),
                    "published_at": source.get("published_at", ""),
                    "source_status": source.get("status", ""),
                }[field]
                if ref.get(field) != expected:
                    raise ValueError(f"selection source {field} mismatch")

    @classmethod
    def _verify_product_sources(
        cls,
        payload: Mapping[str, Any],
        *,
        _seen_paths: set[str] | None = None,
    ) -> None:
        refs = payload.get("source_refs")
        if not isinstance(refs, list) or not refs:
            if payload.get("status") == "NOT_MATERIALIZED":
                return
            raise ValueError("selection source refs are required")
        supply_documents: list[Mapping[str, Any]] = []
        supply_refs: list[Mapping[str, Any]] = []
        for candidate in payload.get("research_candidates", []):
            candidate_refs = candidate.get("source_refs")
            if not isinstance(candidate_refs, list) or not candidate_refs:
                raise ValueError("selection candidate source refs are missing")
            for ref in candidate_refs:
                verified = cls._verify_source_ref(
                    ref,
                    expected_target_trade_date=str(payload["target_trade_date"]),
                )
                if ref.get("type") == RESEARCH_SUPPLY_TYPE:
                    document = verified.get("document")
                    if isinstance(document, Mapping):
                        supply_documents.append(document)
                        supply_refs.append(ref)
                cls._verify_candidate_source_projection(
                    candidate,
                    ref,
                    verified,
                    source_date=str(payload["source_date"]),
                    target_trade_date=str(payload["target_trade_date"]),
                    cutoff_at=str(payload.get("cutoff_at") or ""),
                )
        candidate_source_types = {
            ref.get("type")
            for candidate in payload.get("research_candidates", [])
            for ref in candidate.get("source_refs", [])
            if isinstance(ref, Mapping)
        }
        if candidate_source_types == {RESEARCH_SUPPLY_TYPE}:
            decision_ref = payload.get("manager_decision_ref")
            snapshot_2200 = payload.get("snapshots", {}).get("2200", {})
            if not supply_documents or not supply_refs:
                raise ValueError("research supply source envelope is missing")
            supply_document = supply_documents[0]
            supply_run_id = str(supply_document.get("run_id") or "")
            if any(
                document.get("run_id") != supply_run_id
                or document.get("source_date") != supply_document.get("source_date")
                or document.get("target_trade_date") != supply_document.get("target_trade_date")
                or document.get("frozen_payload_sha256")
                != supply_document.get("frozen_payload_sha256")
                for document in supply_documents
            ):
                raise ValueError("research supply source envelopes are mixed")
            if snapshot_2200.get("status") == "READY" and snapshot_2200.get("run_id") != supply_run_id:
                raise ValueError("research supply 2200 run binding mismatch")
            ready_later = [
                phase
                for phase in ("0830", "0935", "1620")
                if isinstance(payload.get("snapshots", {}).get(phase), Mapping)
                and payload["snapshots"][phase].get("status") == "READY"
            ]
            expected_product_run = (
                str(payload["snapshots"][ready_later[-1]].get("run_id") or "")
                if ready_later
                else supply_run_id
            )
            if payload.get("run_id") != expected_product_run:
                raise ValueError("research supply product run binding mismatch")
            if snapshot_2200.get("status") == "READY":
                if not isinstance(decision_ref, Mapping):
                    raise ValueError("research supply 2200 manager decision reference is missing")
                decision_path_value = decision_ref.get("path")
                if not isinstance(decision_path_value, str) or not decision_path_value:
                    raise ValueError("manager decision reference is missing")
                decision_path = Path(decision_path_value)
                if not decision_path.is_file() or decision_path.is_symlink():
                    raise ValueError("manager decision reference SHA mismatch")
                decision_raw = decision_path.read_bytes()
                if hashlib.sha256(decision_raw).hexdigest() != str(
                    decision_ref.get("raw_sha256") or ""
                ).lower():
                    raise ValueError("manager decision reference SHA mismatch")
                try:
                    decision_document = json.loads(decision_raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ValueError("manager decision document is invalid JSON") from error
                if not isinstance(decision_document, Mapping):
                    raise ValueError("manager decision document is not an object")
                validate_manager_research_decision(
                    decision_document,
                    candidate_ids=[
                        str(candidate["candidate_id"])
                        for candidate in payload.get("research_candidates", [])
                    ],
                    supply_envelope=supply_document,
                )
                cls._verify_manager_qualification_refs(
                    decision_document,
                    source_date=str(payload["source_date"]),
                    target_trade_date=str(payload["target_trade_date"]),
                    candidate_ids=[
                        str(candidate["candidate_id"])
                        for candidate in payload.get("research_candidates", [])
                    ],
                )
                source_ref = supply_refs[0]
                source_ref_path = str(source_ref.get("path") or "")
                if decision_document.get("supply_ref", {}).get("path") != source_ref_path:
                    raise ValueError("manager decision supply path binding mismatch")
                if decision_document.get("supply_ref", {}).get("raw_sha256") != source_ref.get("raw_sha256"):
                    raise ValueError("manager decision supply raw SHA binding mismatch")
                decision_time = str(decision_document.get("generated_at") or "")
                baseline_ids: set[str] | None = None
                if decision_document.get("baseline_ref") is not None:
                    baseline_ids = cls._verify_manager_baseline(
                        decision_document["baseline_ref"],
                        source_date=str(payload["source_date"]),
                        target_trade_date=str(payload["target_trade_date"]),
                        decision_generated_at=decision_time,
                        _seen_paths=_seen_paths,
                    )
                    keep_ids = {row["candidate_id"] for row in decision_document["KEEP"]}
                    add_ids = {row["candidate_id"] for row in decision_document["ADD"]}
                    remove_ids = {row["candidate_id"] for row in decision_document["REMOVE"]}
                    if not keep_ids.issubset(baseline_ids) or remove_ids - baseline_ids:
                        raise ValueError("manager decision baseline KEEP/REMOVE binding mismatch")
                    if add_ids & baseline_ids:
                        raise ValueError("manager decision baseline ADD binding mismatch")
                    expected_decision_ids = sorted((baseline_ids - remove_ids) | add_ids)
                else:
                    expected_decision_ids = sorted(
                        row["candidate_id"]
                        for row in [
                            *decision_document["core"],
                            *decision_document["conditional"],
                        ]
                    )
                decision_core_ids = {
                    row["candidate_id"]
                    for row in [
                        *decision_document["core"],
                        *decision_document["conditional"],
                    ]
                }
                if decision_core_ids != set(expected_decision_ids):
                    raise ValueError("manager decision baseline action set mismatch")
                expected_decision_ids = sorted(expected_decision_ids)
                if snapshot_2200.get("candidate_ids") != expected_decision_ids:
                    raise ValueError("manager decision 2200 candidate binding mismatch")
                if snapshot_2200.get("run_id") != decision_document.get("run_id"):
                    raise ValueError("manager decision 2200 run binding mismatch")
                if snapshot_2200.get("event_at") != decision_document.get("generated_at"):
                    raise ValueError("manager decision 2200 event binding mismatch")
                if snapshot_2200.get("artifact_sha256") != decision_ref.get("raw_sha256"):
                    raise ValueError("manager decision 2200 artifact binding mismatch")
            elif decision_ref is not None:
                raise ValueError("research supply manager decision lacks a READY 2200 snapshot")
        formal = payload.get("formal_authority")
        if (
            isinstance(formal, Mapping)
            and formal.get("status") == "READY"
            and payload.get("formal_shortlist")
        ):
            candidate_ids = list(payload.get("formal_shortlist") or [])
            candidates_by_id = {
                str(candidate.get("candidate_id")): candidate
                for candidate in payload.get("research_candidates", [])
            }
            source_sha256 = str(formal.get("source_sha256") or "")
            for ref in formal.get("evidence_refs", []):
                document = cls._verify_auxiliary_ref(
                    ref,
                    "formal evidence",
                    schema_version="v3_5.selection_formal_evidence.v1",
                    expected_type="EXACT_DATE_PIT",
                    source_date=str(payload["source_date"]),
                    target_trade_date=str(payload["target_trade_date"]),
                    candidate_ids=candidate_ids,
                    source_sha256=source_sha256,
                    expected_run_id=str(ref.get("run_id") or ""),
                )
                if (
                    not isinstance(document, Mapping)
                    or document.get("status") != "READY"
                    or document.get("pit_status") != "READY"
                ):
                    raise ValueError("formal evidence document is not READY")
                cls._verify_formal_candidate_bindings(
                    document,
                    candidates_by_id=candidates_by_id,
                    candidate_ids=candidate_ids,
                    label="formal evidence",
                )
            decision_ref = formal.get("manager_decision_ref")
            decision_document = cls._verify_auxiliary_ref(
                decision_ref,
                "manager decision",
                schema_version="v3_5.selection_manager_decision.v1",
                expected_type="MANAGER_DECISION",
                source_date=str(payload["source_date"]),
                target_trade_date=str(payload["target_trade_date"]),
                candidate_ids=candidate_ids,
                source_sha256=source_sha256,
                expected_run_id=str(decision_ref.get("run_id") or "")
                if isinstance(decision_ref, Mapping)
                else None,
            )
            if not isinstance(decision_document, Mapping) or decision_document.get("decision") is not True:
                raise ValueError("manager decision document is not approved")
            cls._verify_formal_candidate_bindings(
                decision_document,
                candidates_by_id=candidates_by_id,
                candidate_ids=candidate_ids,
                label="manager decision",
            )

    @classmethod
    def _verify_formal_candidate_bindings(
        cls,
        document: Mapping[str, Any],
        *,
        candidates_by_id: Mapping[str, Mapping[str, Any]],
        candidate_ids: list[str],
        label: str,
    ) -> None:
        """Bind formal proof rows to the exact frozen source locators."""

        bindings = document.get("candidate_bindings")
        if not isinstance(bindings, list) or len(bindings) != len(candidate_ids):
            raise ValueError(f"{label} candidate source binding is incomplete")
        seen: list[str] = []
        for binding in bindings:
            if not isinstance(binding, Mapping) or not {
                "candidate_id",
                "eligibility",
                "pit_status",
                "source_refs",
            }.issubset(binding):
                raise ValueError(f"{label} candidate source binding is invalid")
            candidate_id = binding.get("candidate_id")
            if candidate_id not in candidates_by_id or candidate_id in seen:
                raise ValueError(f"{label} candidate source binding identity is invalid")
            seen.append(candidate_id)
            candidate = candidates_by_id[candidate_id]
            if (
                binding.get("eligibility") != candidate.get("eligibility")
                or binding.get("pit_status") != candidate.get("pit_status")
            ):
                raise ValueError(f"{label} candidate source proof status mismatch")
            source_refs = binding.get("source_refs")
            candidate_refs = candidate.get("source_refs")
            if (
                not isinstance(source_refs, list)
                or not isinstance(candidate_refs, list)
                or any(not isinstance(ref, Mapping) for ref in source_refs)
                or any(not isinstance(ref, Mapping) for ref in candidate_refs)
            ):
                raise ValueError(f"{label} candidate source binding refs are invalid")
            if [cls._source_ref_identity(ref) for ref in source_refs] != [
                cls._source_ref_identity(ref) for ref in candidate_refs
            ]:
                raise ValueError(f"{label} candidate source binding refs mismatch")
        if seen != candidate_ids:
            raise ValueError(f"{label} candidate source binding order mismatch")

    @classmethod
    def _verify_manager_baseline(
        cls,
        baseline_ref: Any,
        *,
        source_date: str,
        target_trade_date: str,
        decision_generated_at: str,
        _seen_paths: set[str] | None = None,
    ) -> set[str]:
        """Verify a real prior manager snapshot used by KEEP/ADD/REMOVE."""

        if not isinstance(baseline_ref, Mapping):
            raise ValueError("manager decision baseline reference is missing")
        path_value = baseline_ref.get("path")
        if not isinstance(path_value, str) or not path_value:
            raise ValueError("manager decision baseline path is missing")
        path = Path(path_value)
        if not path.is_file() or path.is_symlink():
            raise ValueError("manager decision baseline SHA mismatch")
        path_key = str(path)
        seen_paths = set(_seen_paths or set())
        if path_key in seen_paths:
            raise ValueError("manager decision baseline reference cycle")
        seen_paths.add(path_key)
        baseline_raw = path.read_bytes()
        if hashlib.sha256(baseline_raw).hexdigest() != str(
            baseline_ref.get("raw_sha256") or ""
        ).lower():
            raise ValueError("manager decision baseline SHA mismatch")
        try:
            baseline = json.loads(baseline_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("manager decision baseline is invalid JSON") from error
        if not isinstance(baseline, Mapping):
            raise ValueError("manager decision baseline is not an object")
        if baseline.get("source_date") != source_date:
            raise ValueError("manager decision baseline source date mismatch")
        if baseline.get("target_trade_date") != target_trade_date:
            raise ValueError("manager decision baseline target date mismatch")
        baseline_time = baseline.get("generated_at") or baseline.get("event_at")
        if not isinstance(baseline_time, str) or not baseline_time:
            raise ValueError("manager decision baseline timestamp is missing")
        try:
            prior = datetime.fromisoformat(baseline_time.replace("Z", "+00:00"))
            current = datetime.fromisoformat(decision_generated_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("manager decision baseline timestamp is invalid") from error
        if (
            prior.tzinfo is None
            or prior.utcoffset() is None
            or current.tzinfo is None
            or current.utcoffset() is None
            or prior.astimezone(_SHANGHAI) >= current.astimezone(_SHANGHAI)
        ):
            raise ValueError("manager decision baseline is not earlier than decision")

        schema_version = baseline.get("schema_version")
        if schema_version == SELECTION_SCHEMA_VERSION:
            try:
                validate_selection_research_product(baseline)
            except ValueError as error:
                raise ValueError("manager decision baseline selection product is invalid") from error
            try:
                cls._verify_product_sources(baseline, _seen_paths=seen_paths)
            except ValueError as error:
                raise ValueError("manager decision baseline selection source is invalid") from error
            manager_proof = baseline.get("manager_decision_ref")
            formal_authority = baseline.get("formal_authority")
            if isinstance(manager_proof, Mapping):
                proof_ids = cls._verify_manager_baseline(
                    manager_proof,
                    source_date=source_date,
                    target_trade_date=target_trade_date,
                    decision_generated_at=decision_generated_at,
                    _seen_paths=seen_paths,
                )
            elif (
                isinstance(formal_authority, Mapping)
                and formal_authority.get("status") == "READY"
                and baseline.get("formal_shortlist")
                and isinstance(formal_authority.get("manager_decision_ref"), Mapping)
            ):
                # _verify_product_sources above has already verified the
                # structured formal manager proof and its candidate bindings.
                proof_ids = set(baseline["formal_shortlist"])
            else:
                raise ValueError("manager decision baseline lacks a real manager proof")
            snapshots = baseline.get("snapshots")
            if not isinstance(snapshots, Mapping):
                raise ValueError("manager decision baseline snapshots are missing")
            ready_phases = [
                phase
                for phase in ("2200", "0830", "0935", "1620")
                if isinstance(snapshots.get(phase), Mapping)
                and snapshots[phase].get("status") == "READY"
            ]
            if not ready_phases:
                raise ValueError("manager decision baseline has no READY snapshot")
            snapshot = snapshots[ready_phases[-1]]
            candidate_ids = snapshot.get("candidate_ids")
            if not isinstance(candidate_ids, list):
                raise ValueError("manager decision baseline candidate set is invalid")
            if len(candidate_ids) != len(set(candidate_ids)):
                raise ValueError("manager decision baseline candidate set is invalid")
            if isinstance(manager_proof, Mapping) and set(candidate_ids) != proof_ids:
                raise ValueError("manager decision baseline manager proof set mismatch")
            return set(candidate_ids)

        if schema_version != MANAGER_DECISION_SCHEMA_VERSION:
            raise ValueError("manager decision baseline schema is not an accepted product")
        baseline_supply_ref = baseline.get("supply_ref")
        if not isinstance(baseline_supply_ref, Mapping):
            raise ValueError("manager decision baseline supply reference is missing")
        baseline_supply_path_value = baseline_supply_ref.get("path")
        if not isinstance(baseline_supply_path_value, str) or not baseline_supply_path_value:
            raise ValueError("manager decision baseline supply path is missing")
        baseline_supply_path = Path(baseline_supply_path_value)
        if not baseline_supply_path.is_file() or baseline_supply_path.is_symlink():
            raise ValueError("manager decision baseline supply is unavailable")
        baseline_supply_raw = baseline_supply_path.read_bytes()
        baseline_supply_sha = hashlib.sha256(baseline_supply_raw).hexdigest()
        if baseline_supply_sha != str(baseline_supply_ref.get("raw_sha256") or "").lower():
            raise ValueError("manager decision baseline supply SHA mismatch")
        try:
            baseline_supply_document = json.loads(baseline_supply_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("manager decision baseline supply is invalid JSON") from error
        if not isinstance(baseline_supply_document, Mapping):
            raise ValueError("manager decision baseline supply is not an object")
        baseline_run_id = baseline.get("run_id")
        validate_research_supply_envelope(
            baseline_supply_document,
            expected_source_date=source_date,
            expected_target_trade_date=target_trade_date,
            expected_run_id=baseline_run_id,
        )
        if baseline_supply_ref.get("run_id") != baseline_run_id:
            raise ValueError("manager decision baseline supply run binding mismatch")
        if baseline_supply_ref.get("frozen_payload_sha256") != baseline_supply_document.get(
            "frozen_payload_sha256"
        ):
            raise ValueError("manager decision baseline supply frozen SHA mismatch")
        baseline_cards = baseline_supply_document["frozen_payload"].get("event_cards")
        if not isinstance(baseline_cards, list):
            raise ValueError("manager decision baseline supply cards are invalid")
        baseline_candidate_ids: list[str] = []
        for card in baseline_cards:
            ticker = str(card.get("ticker") or "") if isinstance(card, Mapping) else ""
            if not re.fullmatch(r"\d{5}\.HK", ticker):
                raise ValueError("manager decision baseline supply card is invalid")
            candidate_id = f"HK.{ticker.split('.')[0]}|{ticker}"
            if candidate_id in baseline_candidate_ids:
                raise ValueError("manager decision baseline supply candidate is duplicated")
            baseline_candidate_ids.append(candidate_id)
        decision_ids = [
            row.get("candidate_id")
            for row in [*(baseline.get("core") or []), *(baseline.get("conditional") or [])]
            if isinstance(row, Mapping)
        ]
        if len(decision_ids) != len(
            [row for row in [*(baseline.get("core") or []), *(baseline.get("conditional") or [])] if isinstance(row, Mapping)]
        ):
            raise ValueError("manager decision baseline candidate set is invalid")
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("manager decision baseline candidate set is invalid")
        validate_manager_research_decision(
            baseline,
            candidate_ids=baseline_candidate_ids,
            supply_envelope=baseline_supply_document,
        )
        if set(decision_ids) - set(baseline_candidate_ids):
            raise ValueError("manager decision baseline supply candidate binding mismatch")
        predecessor_ids: set[str] | None = None
        if baseline.get("baseline_ref") is not None:
            predecessor_ids = cls._verify_manager_baseline(
                baseline["baseline_ref"],
                source_date=source_date,
                target_trade_date=target_trade_date,
                decision_generated_at=str(baseline["generated_at"]),
                _seen_paths=seen_paths,
            )
        keep_ids = {row["candidate_id"] for row in baseline["KEEP"]}
        add_ids = {row["candidate_id"] for row in baseline["ADD"]}
        remove_ids = {row["candidate_id"] for row in baseline["REMOVE"]}
        if predecessor_ids is None:
            expected_ids = add_ids
        else:
            if not keep_ids.issubset(predecessor_ids) or remove_ids - predecessor_ids:
                raise ValueError("manager decision baseline action set mismatch")
            if add_ids & predecessor_ids:
                raise ValueError("manager decision baseline action set mismatch")
            expected_ids = (predecessor_ids - remove_ids) | add_ids
        if set(decision_ids) != expected_ids:
            raise ValueError("manager decision baseline action set mismatch")
        return set(decision_ids)

    @classmethod
    def _verify_manager_qualification_refs(
        cls,
        decision: Mapping[str, Any],
        *,
        source_date: str,
        target_trade_date: str,
        candidate_ids: list[str],
    ) -> None:
        """Check bytes for optional qualifications without promoting them."""

        for ref in decision.get("qualification_refs", []):
            if not isinstance(ref, Mapping):
                raise ValueError("manager qualification reference is invalid")
            path_value = ref.get("path")
            raw_sha = ref.get("raw_sha256")
            if path_value is None and raw_sha is None:
                continue
            if not isinstance(path_value, str) or not path_value:
                raise ValueError("manager qualification path is missing")
            path = Path(path_value)
            if not path.is_file() or path.is_symlink():
                raise ValueError("manager qualification SHA mismatch")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != str(raw_sha or "").lower():
                raise ValueError("manager qualification SHA mismatch")
            try:
                document = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("manager qualification document is invalid JSON") from error
            if not isinstance(document, Mapping):
                raise ValueError("manager qualification document is not an object")
            if document.get("schema_version") != "v3_5.selection_formal_evidence.v1" or document.get("type") != "EXACT_DATE_PIT":
                raise ValueError("manager qualification document schema is invalid")
            if (
                document.get("source_date") != source_date
                or document.get("target_trade_date") != target_trade_date
            ):
                raise ValueError("manager qualification document date binding mismatch")
            documented_ids = document.get("candidate_ids")
            candidate_id = ref.get("candidate_id")
            if candidate_id not in candidate_ids:
                raise ValueError("manager qualification candidate is unknown")
            if not isinstance(documented_ids, list) or candidate_id not in documented_ids:
                raise ValueError("manager qualification document candidate binding mismatch")
            if document.get("status") not in {"READY", "ELIGIBLE"}:
                raise ValueError("manager qualification document status is invalid")
            if "pit_status" in document and document.get("pit_status") != "READY":
                raise ValueError("manager qualification document PIT status is invalid")
            bindings = document.get("candidate_bindings")
            if bindings is not None:
                if not isinstance(bindings, list):
                    raise ValueError("manager qualification document bindings are invalid")
                matching = [
                    binding
                    for binding in bindings
                    if isinstance(binding, Mapping)
                    and binding.get("candidate_id") == candidate_id
                ]
                if not matching or any(
                    binding.get("eligibility") != "ELIGIBLE"
                    or binding.get("pit_status") != "READY"
                    or not isinstance(binding.get("source_refs"), list)
                    or not binding["source_refs"]
                    for binding in matching
                ):
                    raise ValueError("manager qualification document proof is incomplete")

    @classmethod
    def _verify_auxiliary_ref(
        cls,
        ref: Any,
        label: str,
        *,
        schema_version: str | None = None,
        expected_type: str | None = None,
        source_date: str | None = None,
        target_trade_date: str | None = None,
        candidate_ids: list[str] | None = None,
        source_sha256: str | None = None,
        expected_run_id: str | None = None,
    ) -> Mapping[str, Any] | None:
        if not isinstance(ref, Mapping) or not isinstance(ref.get("path"), str) or not ref["path"]:
            raise ValueError(f"{label} reference is missing")
        path = Path(ref["path"])
        if not path.is_file() or path.is_symlink() or cls._raw_sha(path) != str(ref.get("sha256") or "").lower():
            raise ValueError(f"{label} reference SHA mismatch")
        if schema_version is None and expected_type is None:
            return None
        try:
            document = json.loads(path.read_bytes().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"{label} document is not valid JSON") from error
        if not isinstance(document, Mapping):
            raise ValueError(f"{label} document is not an object")
        required = {
            "schema_version",
            "type",
            "source_sha256",
            "source_date",
            "target_trade_date",
            "run_id",
            "candidate_ids",
        }
        if not required.issubset(document):
            raise ValueError(f"{label} document schema is incomplete")
        if schema_version is not None and document.get("schema_version") != schema_version:
            raise ValueError(f"{label} document schema is invalid")
        if expected_type is not None and document.get("type") != expected_type:
            raise ValueError(f"{label} document type is invalid")
        if source_sha256 is not None and document.get("source_sha256") != source_sha256:
            raise ValueError(f"{label} document source binding mismatch")
        if source_date is not None and document.get("source_date") != source_date:
            raise ValueError(f"{label} document source date mismatch")
        if target_trade_date is not None and document.get("target_trade_date") != target_trade_date:
            raise ValueError(f"{label} document target date mismatch")
        if expected_run_id is not None and document.get("run_id") != expected_run_id:
            raise ValueError(f"{label} document run binding mismatch")
        if candidate_ids is not None and document.get("candidate_ids") != candidate_ids:
            raise ValueError(f"{label} document candidate binding mismatch")
        return document

    def _read_date_current(self, target_trade_date: str) -> dict[str, Any] | None:
        value, _ = self._read_date_current_snapshot(target_trade_date)
        return value

    def _read_date_current_snapshot(
        self,
        target_trade_date: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        relative = self._date_current_relative(target_trade_date)
        path = self._path(relative)
        if not path.is_file():
            if path.exists():
                raise ValueError("selection current pointer is not a file")
            return None, None
        raw = path.read_bytes()
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("selection current pointer is invalid JSON") from error
        self._validate_current(value, target_trade_date=target_trade_date)
        return value, hashlib.sha256(raw).hexdigest()

    def _read_run(self, target_trade_date: str, run_id: str) -> dict[str, Any]:
        if not self._RUN_ID.fullmatch(run_id):
            raise ValueError("invalid selection run_id")
        artifact_relative = self._artifact_relative(target_trade_date, run_id)
        receipt_relative = self._receipt_relative(target_trade_date, run_id)
        run_manifest_relative = self._run_manifest_relative(target_trade_date, run_id)
        artifact_path = self._path(artifact_relative)
        receipt_path = self._path(receipt_relative)
        if not artifact_path.is_file() or not receipt_path.is_file():
            raise ValueError("selection artifact or receipt is missing")
        payload = self._read(artifact_relative)
        artifact_sha = self._raw_sha(artifact_path)
        manifest = self._manifest()
        run_manifest_path = self._path(run_manifest_relative)
        if not run_manifest_path.is_file():
            raise ValueError("selection run manifest is missing")
        run_manifest = self._read(run_manifest_relative)
        self._validate_manifest(run_manifest)
        run_manifest_sha = self._raw_sha(run_manifest_path)
        if (
            run_manifest["entries"].get(artifact_relative) != artifact_sha
            or manifest["entries"].get(artifact_relative) != artifact_sha
            or manifest["entries"].get(run_manifest_relative) != run_manifest_sha
        ):
            raise ValueError("selection artifact manifest mismatch")
        receipt = self._read(receipt_relative)
        receipt_sha = self._raw_sha(receipt_path)
        if (
            run_manifest["entries"].get(receipt_relative) != receipt_sha
            or manifest["entries"].get(receipt_relative) != receipt_sha
            or receipt != self._receipt(payload, artifact_relative, artifact_sha)
        ):
            raise ValueError("selection receipt manifest mismatch")
        if validate_selection_research_product(payload) != target_trade_date or payload.get("run_id") != run_id:
            raise ValueError("selection artifact identity mismatch")
        self._verify_product_sources(payload)
        return payload

    def _read_current_run(
        self,
        target_trade_date: str,
        current: Mapping[str, Any],
        *,
        current_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Read a current target only after checking every pointer SHA binding."""

        run_id = str(current["run_id"])
        payload = self._read_run(target_trade_date, run_id)
        artifact_path = self._path(str(current["artifact_path"]))
        receipt_path = self._path(str(current["receipt_path"]))
        manifest_path = self._path(str(current["manifest_path"]))
        actual = {
            "artifact_sha256": self._raw_sha(artifact_path),
            "receipt_sha256": self._raw_sha(receipt_path),
            "manifest_sha256": self._raw_sha(manifest_path),
        }
        for field, digest in actual.items():
            if current.get(field) != digest:
                raise ValueError(f"selection current {field} binding mismatch")
        if current.get("target_trade_date") != target_trade_date:
            raise ValueError("selection current target date mismatch")
        if current.get("run_id") != payload.get("run_id") or current.get("generated_at") != payload.get("generated_at"):
            raise ValueError("selection current run identity binding mismatch")
        if current_sha256 is not None:
            current_path = self._path(self._date_current_relative(target_trade_date))
            if self._raw_sha(current_path) != current_sha256:
                raise ValueError("selection current pointer changed during read")
        global_path = self._path(self._CURRENT_RELATIVE)
        if global_path.is_file():
            global_current = self._read(self._CURRENT_RELATIVE)
            self._validate_global_current(global_current)
            if global_current.get("target_trade_date") == target_trade_date:
                if (
                    global_current.get("run_id") != current.get("run_id")
                    or global_current.get("artifact_sha256") != current.get("artifact_sha256")
                ):
                    raise ValueError("selection global current binding mismatch")
        elif global_path.exists():
            raise ValueError("selection global current pointer is not a file")
        return payload

    def publish(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Publish one immutable run and advance only the selection current pointer."""

        target_trade_date = validate_selection_research_product(payload)
        run_id = str(payload["run_id"])
        if not self._RUN_ID.fullmatch(run_id):
            raise ValueError("invalid selection run_id")
        self._verify_product_sources(payload)
        artifact_relative = self._artifact_relative(target_trade_date, run_id)
        receipt_relative = self._receipt_relative(target_trade_date, run_id)
        run_manifest_relative = self._run_manifest_relative(target_trade_date, run_id)
        artifact_sha = self._canonical_sha(payload)
        receipt = self._receipt(payload, artifact_relative, artifact_sha)
        receipt_sha = self._canonical_sha(receipt)
        run_manifest = {
            "schema_version": "v3_5.selection_manifest.v1",
            "namespace": self._SELECTION_ROOT,
            "entries": {
                artifact_relative: artifact_sha,
                receipt_relative: receipt_sha,
            },
        }
        run_manifest_sha = self._canonical_sha(run_manifest)
        with self._lock():
            old_current = self._read_date_current(target_trade_date)
            old_payload = None
            if old_current is not None:
                old_payload = self._read_current_run(target_trade_date, old_current)
                if str(old_current["generated_at"]) > str(payload["generated_at"]):
                    raise ValueError("selection current cannot move backwards")
                old_snapshots = old_payload.get("snapshots", {})
                new_snapshots = payload.get("snapshots", {})
                for phase in ("2200", "0830", "0935", "1620"):
                    if old_snapshots.get(phase, {}).get("status") == "READY" and old_snapshots.get(phase) != new_snapshots.get(phase):
                        raise ValueError(f"selection {phase} snapshot is immutable")
            manifest = self._manifest()
            entries = dict(manifest["entries"])
            existing = entries.get(artifact_relative)
            artifact_path = self._path(artifact_relative)
            receipt_path = self._path(receipt_relative)
            run_manifest_path = self._path(run_manifest_relative)
            if existing and existing != artifact_sha:
                raise ValueError("conflicting selection run")
            if existing:
                if (
                    entries.get(artifact_relative) != artifact_sha
                    or entries.get(receipt_relative) != receipt_sha
                    or entries.get(run_manifest_relative) != run_manifest_sha
                    or not artifact_path.is_file()
                    or self._raw_sha(artifact_path) != artifact_sha
                    or not receipt_path.is_file()
                    or self._raw_sha(receipt_path) != receipt_sha
                    or self._read(receipt_relative) != receipt
                    or not run_manifest_path.is_file()
                    or self._raw_sha(run_manifest_path) != run_manifest_sha
                    or self._read(run_manifest_relative) != run_manifest
                ):
                    raise ValueError("selection existing artifact integrity mismatch")
            else:
                if artifact_path.exists() or receipt_path.exists() or run_manifest_path.exists():
                    raise ValueError("orphan selection artifact or receipt")
                self._write(artifact_relative, payload)
                self._write(receipt_relative, receipt)
                self._write(run_manifest_relative, run_manifest)
                entries[artifact_relative] = artifact_sha
                entries[receipt_relative] = receipt_sha
                entries[run_manifest_relative] = run_manifest_sha
                manifest = {**manifest, "entries": entries}
                self._write_manifest(manifest)
            if existing and entries.get(run_manifest_relative) != run_manifest_sha:
                raise ValueError("selection run manifest index mismatch")
            manifest_sha = self._raw_sha(run_manifest_path)
            date_current_relative = self._date_current_relative(target_trade_date)
            date_current = self._current_pointer(
                payload,
                artifact_relative=artifact_relative,
                artifact_sha=artifact_sha,
                receipt_relative=receipt_relative,
                receipt_sha=receipt_sha,
                manifest_relative=run_manifest_relative,
                manifest_sha=manifest_sha,
            )
            current_updated = old_current != date_current
            if current_updated:
                self._write(date_current_relative, date_current)
            global_relative = self._CURRENT_RELATIVE
            global_path = self._path(global_relative)
            global_updated = False
            global_pointer = self._global_current_pointer(date_current)
            if global_path.is_file():
                old_global = self._read(global_relative)
                self._validate_global_current(old_global)
                if str(old_global["target_trade_date"]) > target_trade_date:
                    global_pointer = old_global
                elif str(old_global["target_trade_date"]) == target_trade_date and old_global == global_pointer:
                    global_pointer = old_global
                else:
                    global_updated = old_global != global_pointer
            elif global_path.exists():
                raise ValueError("selection global current pointer is not a file")
            else:
                global_updated = True
            if global_updated:
                self._write(global_relative, global_pointer)
        return {
            "target_trade_date": target_trade_date,
            "run_id": run_id,
            "artifact_path": artifact_relative,
            "artifact_sha256": artifact_sha,
            "receipt_path": receipt_relative,
            "receipt_sha256": receipt_sha,
            "manifest_path": run_manifest_relative,
            "manifest_sha256": run_manifest_sha,
            "current_path": date_current_relative,
            "current_sha256": self._raw_sha(self._path(date_current_relative)),
            "global_current_path": global_relative,
            "global_current_sha256": self._raw_sha(self._path(global_relative)),
            "current_updated": current_updated,
            "global_current_updated": global_updated,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def read_exact(self, target_trade_date: str) -> dict[str, Any] | None:
        target_trade_date = _date(target_trade_date)
        current, current_sha256 = self._read_date_current_snapshot(target_trade_date)
        if current is None:
            prefix = f"{self._SELECTION_ROOT}/{target_trade_date}/"
            if any(str(path).startswith(prefix) for path in self._manifest()["entries"]):
                raise ValueError("selection artifact exists without current pointer")
            return None
        return self._read_current_run(
            target_trade_date,
            current,
            current_sha256=current_sha256,
        )

    def read_run(self, target_trade_date: str, run_id: str) -> dict[str, Any]:
        return self._read_run(_date(target_trade_date), run_id)

    def read_lineage(self, target_trade_date: str) -> dict[str, Any] | None:
        target_trade_date = _date(target_trade_date)
        _, lineage = self.read_exact_with_lineage(target_trade_date)
        return lineage

    def read_exact_with_lineage(
        self,
        target_trade_date: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        target_trade_date = _date(target_trade_date)
        current, current_sha256 = self._read_date_current_snapshot(target_trade_date)
        if current is None:
            prefix = f"{self._SELECTION_ROOT}/{target_trade_date}/"
            if any(str(path).startswith(prefix) for path in self._manifest()["entries"]):
                raise ValueError("selection artifact exists without current pointer")
            return None, None
        payload = self._read_current_run(
            target_trade_date,
            current,
            current_sha256=current_sha256,
        )
        manifest_path = self._path(str(current["manifest_path"]))
        lineage = {
            "artifact_path": current["artifact_path"],
            "artifact_sha256": current["artifact_sha256"],
            "receipt_path": current["receipt_path"],
            "receipt_sha256": current["receipt_sha256"],
            "manifest_path": current["manifest_path"],
            "manifest_sha256": self._raw_sha(manifest_path),
            "current_path": self._date_current_relative(target_trade_date),
            "current_sha256": current_sha256,
            "run_id": current["run_id"],
            "target_trade_date": target_trade_date,
        }
        return payload, lineage

    def append_phase(
        self,
        target_trade_date: str,
        phase: str,
        *,
        run_id: str,
        event_at: str,
        artifact_sha256: str,
        changes: list[Mapping[str, Any]] | None = None,
        observation: Mapping[str, Any] | None = None,
        outcome: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        base = self.read_exact(target_trade_date)
        if base is None:
            raise ValueError("selection base ledger is not materialized")
        next_product = append_selection_phase(
            base,
            phase,
            run_id=run_id,
            event_at=event_at,
            artifact_sha256=artifact_sha256,
            changes=changes,
            observation=observation,
            outcome=outcome,
        )
        return self.publish(next_product)


class HourlyResearchStore(NativeDataStore):
    """Immutable per-slot research artifacts with a LIVE-only latest pointer."""

    def _path(self, relative: str) -> Path:
        return resolve_owned_path(self.root, relative)

    @staticmethod
    def _relative(archive_date: str, slot: str, mode: str) -> str:
        return f"research/hourly/{mode.lower()}/{archive_date}/{slot}.json"

    @staticmethod
    def _receipt_relative(archive_date: str, slot: str, mode: str) -> str:
        return f"receipts/research/hourly/{mode.lower()}/{archive_date}/{slot}.json"

    @staticmethod
    def _history_relative(
        archive_date: str, slot: str, mode: str, digest: str
    ) -> str:
        return (
            "research/hourly/history/"
            f"{mode.lower()}/{archive_date}/{slot}/{digest}.json"
        )

    @staticmethod
    def _history_receipt_relative(
        archive_date: str, slot: str, mode: str, digest: str
    ) -> str:
        return (
            "receipts/research/hourly/history/"
            f"{mode.lower()}/{archive_date}/{slot}/{digest}.json"
        )

    @staticmethod
    def _supersession_relative(
        archive_date: str, slot: str, mode: str, digest: str
    ) -> str:
        return (
            "receipts/research/hourly/supersessions/"
            f"{mode.lower()}/{archive_date}/{slot}/{digest}.json"
        )

    @staticmethod
    def _hourly_manifest_position(relative: str) -> tuple[str, str] | None:
        """Return the slot position encoded by an hourly manifest entry."""

        match = re.search(
            r"/hourly/(?:live|history/live|supersessions/live|"
            r"transform-validation/live)/(\d{8})/(\d{4})(?:/|\.json$)",
            str(relative),
        )
        if match is None:
            return None
        return match.group(1), match.group(2)

    def _manifest_before_hourly_latest(
        self,
        manifest: Mapping[str, str],
        previous_latest: Mapping[str, Any] | None,
    ) -> dict[str, str]:
        """Remove only hourly entries published after the captured latest.

        A late retry can observe newer hourly slots in the shared manifest.
        Those entries were published after the hourly CAS and therefore do
        not belong to the manifest hash captured in its supersession.  The
        captured latest pointer is the boundary for this deterministic
        reconstruction; the caller still compares the resulting hash with
        the committed preimage hash.
        """

        candidate = dict(manifest)
        if previous_latest is None:
            return candidate
        previous_position = (
            str(previous_latest["archive_date"]),
            str(previous_latest["slot"]),
        )
        for relative in list(candidate):
            position = self._hourly_manifest_position(relative)
            if position is not None and position > previous_position:
                candidate.pop(relative, None)
        return candidate

    def _validate_hourly_latest_proof(
        self,
        manifest: Mapping[str, str],
        *,
        archive_date: str,
        slot: str,
        current_digest: str,
        previous_digest: str,
        previous_manifest: Mapping[str, str],
        previous_latest: Mapping[str, Any] | None,
        latest_current: Mapping[str, Any] | None,
    ) -> None:
        """Bind LIVE latest pointers to the manifest preimage and progression."""

        relative = self._relative(archive_date, slot, "LIVE")
        target_position = (archive_date, slot)

        def _validate_manifest_pointer(
            pointer: Mapping[str, Any],
            source_manifest: Mapping[str, str],
            *,
            allow_replaced_target: bool = False,
        ) -> tuple[str, str]:
            self._validate_pointer(pointer)
            pointer_path = str(pointer["payload_path"])
            pointer_sha = str(pointer["payload_sha256"]).lower()
            pointer_position = (str(pointer["archive_date"]), str(pointer["slot"]))
            if source_manifest.get(pointer_path) != pointer_sha:
                raise ValueError(
                    "hourly research latest pointer is not bound to manifest"
                )
            if not allow_replaced_target or pointer_path != relative:
                payload_path = self._path(pointer_path)
                if not payload_path.is_file() or _sha256(self._read(pointer_path)) != pointer_sha:
                    raise ValueError(
                        "hourly research latest pointer payload is not bound"
                    )
            return pointer_position

        previous_position = None
        if previous_latest is not None:
            previous_position = _validate_manifest_pointer(
                previous_latest,
                previous_manifest,
                allow_replaced_target=True,
            )
            if previous_position == target_position and str(
                previous_latest["payload_sha256"]
            ).lower() != previous_digest:
                raise ValueError(
                    "hourly research previous latest pointer is not deterministic"
                )

        if latest_current is not None:
            current_position = _validate_manifest_pointer(
                latest_current,
                manifest,
                allow_replaced_target=True,
            )
        else:
            current_position = None

        if current_position is None:
            raise ValueError("hourly research latest pointer did not advance")
        if current_position == target_position:
            if str(latest_current["payload_sha256"]).lower() != current_digest:
                raise ValueError("hourly research latest pointer mismatch")
            return
        if current_position <= target_position:
            raise ValueError("hourly research latest pointer did not advance")
        if previous_position is None or current_position < previous_position:
            raise ValueError("hourly research previous latest pointer progression mismatch")


    def _previous_manifest_for_recovery(
        self,
        manifest: Mapping[str, str],
        *,
        archive_date: str,
        relative: str,
        previous_digest: str,
        expected_sha256: str,
        previous_latest: Mapping[str, Any] | None = None,
        expected_reason: str | None = None,
        expected_source_provenance: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        """Reconstruct the manifest snapshot captured before hourly CAS.

        A successful 2100 retry updates the generic archive in a second CAS,
        which changes the shared manifest after the hourly supersession was
        recorded.  The generic supersession receipt provides the one
        deterministic bridge back to the manifest state seen by the hourly
        CAS.  No old hourly payload or receipt is rewritten.
        """

        candidate = dict(manifest)
        candidate[relative] = previous_digest
        if _sha256(candidate) == expected_sha256:
            return candidate

        # Newer hourly slots may have been published after this CAS.  Rebuild
        # the captured preimage at the recorded latest boundary, then retain
        # the same hash gate.  A tampered boundary cannot manufacture a
        # matching preimage because only entries after that exact pointer are
        # removed.
        if previous_latest is not None:
            self._validate_pointer(previous_latest)
            candidate = self._manifest_before_hourly_latest(manifest, previous_latest)
            candidate[relative] = previous_digest
            if _sha256(candidate) == expected_sha256:
                return candidate

        generic_relative = ResearchArchiveStore._relative(archive_date)
        generic_digest = str(manifest.get(generic_relative) or "").lower()
        if not _SHA256.fullmatch(generic_digest):
            raise ValueError("hourly research previous manifest proof is unavailable")
        generic_payload_path = self._path(generic_relative)
        generic_receipt_relative = ResearchArchiveStore._receipt_relative(archive_date)
        generic_receipt_path = self._path(generic_receipt_relative)
        if not generic_payload_path.is_file() or not generic_receipt_path.is_file():
            raise ValueError("hourly research generic manifest bridge is incomplete")
        generic_payload = self._read(generic_relative)
        generic_receipt = self._read(generic_receipt_relative)
        if (
            _sha256(generic_payload) != generic_digest
            or validate_research_archive(generic_payload) != archive_date
            or generic_receipt
            != ResearchArchiveStore._receipt(generic_payload, generic_digest)
        ):
            raise ValueError("hourly research generic manifest bridge mismatch")
        generic_supersession_relative = ResearchArchiveStore._supersession_relative(
            archive_date, generic_digest
        )
        generic_supersession_path = self._path(generic_supersession_relative)
        if not generic_supersession_path.is_file():
            raise ValueError("hourly research generic supersession bridge is missing")
        generic_supersession = self._read(generic_supersession_relative)
        if not isinstance(generic_supersession, Mapping):
            raise ValueError("hourly research generic supersession bridge is invalid")
        generic_previous = str(
            generic_supersession.get("previous_payload_sha256") or ""
        ).lower()
        generic_history_relative = ResearchArchiveStore._history_relative(
            archive_date, generic_previous
        )
        generic_history_receipt_relative = ResearchArchiveStore._history_receipt_relative(
            archive_date, generic_previous
        )
        generic_history_path = self._path(generic_history_relative)
        generic_history_receipt_path = self._path(generic_history_receipt_relative)
        if not _SHA256.fullmatch(generic_previous) or not generic_history_path.is_file() or not generic_history_receipt_path.is_file():
            raise ValueError("hourly research generic manifest bridge history is incomplete")
        generic_previous_payload = self._read(generic_history_relative)
        generic_previous_receipt = self._read(generic_history_receipt_relative)
        if (
            _sha256(generic_previous_payload) != generic_previous
            or validate_research_archive(generic_previous_payload) != archive_date
            or generic_previous_receipt
            != ResearchArchiveStore._receipt(generic_previous_payload, generic_previous)
            or generic_supersession.get("schema_version")
            != "v3_5.research_archive_supersession.v1"
            or generic_supersession.get("archive_date") != archive_date
            or generic_supersession.get("mode") != "LIVE"
            or generic_supersession.get("payload_path") != generic_relative
            or generic_supersession.get("payload_sha256") != generic_digest
            or generic_supersession.get("previous_payload_path")
            != generic_history_relative
            or generic_supersession.get("previous_payload_sha256")
            != generic_previous
            or generic_supersession.get("previous_receipt_path")
            != generic_history_receipt_relative
            or generic_supersession.get("previous_receipt_sha256")
            != _sha256(generic_previous_receipt)
        ):
            raise ValueError("hourly research generic supersession bridge mismatch")
        bridge = dict(manifest)
        bridge[generic_relative] = generic_previous
        if generic_supersession.get("previous_manifest_sha256") != _sha256(bridge):
            if previous_latest is None:
                raise ValueError("hourly research generic manifest bridge mismatch")
            bridge = self._manifest_before_hourly_latest(manifest, previous_latest)
            bridge[generic_relative] = generic_previous
            if generic_supersession.get("previous_manifest_sha256") != _sha256(bridge):
                raise ValueError("hourly research generic manifest bridge mismatch")
        bridge[relative] = previous_digest
        if _sha256(bridge) != expected_sha256:
            raise ValueError("hourly research previous manifest mismatch")

        generic_current_source = str(
            generic_payload.get("source_input_sha256") or ""
        ).lower()
        generic_previous_source = str(
            generic_previous_payload.get("source_input_sha256") or ""
        ).lower()
        generic_previous_latest = generic_supersession.get("previous_latest_pointer")
        if generic_previous_latest is not None:
            ResearchArchiveStore._validate_pointer(generic_previous_latest)
            if generic_previous_latest != ResearchArchiveStore._latest_pointer(
                archive_date, generic_previous
            ):
                raise ValueError("hourly research generic previous latest mismatch")
        if (
            any(
                field not in generic_supersession
                for field in (
                    "source_input_sha256",
                    "previous_source_input_sha256",
                    "reason",
                    "source_provenance",
                    "previous_latest_pointer",
                    "previous_latest_pointer_sha256",
                    "write_policy",
                    "production_allowed",
                    "buy_gate_updated",
                    "orders_sent",
                )
            )
            or
            str(generic_supersession.get("source_input_sha256") or "").lower()
            != generic_current_source
            or str(
                generic_supersession.get("previous_source_input_sha256") or ""
            ).lower()
            != generic_previous_source
            or (
                expected_reason is not None
                and generic_supersession.get("reason") != expected_reason
            )
            or (
                expected_source_provenance is not None
                and generic_supersession.get("source_provenance")
                != dict(expected_source_provenance)
            )
            or generic_supersession.get("previous_latest_pointer_sha256")
            != (
                _sha256(generic_previous_latest)
                if generic_previous_latest is not None
                else ""
            )
            or generic_supersession.get("write_policy") != "read_only"
            or generic_supersession.get("production_allowed") is not False
            or generic_supersession.get("buy_gate_updated") is not False
            or generic_supersession.get("orders_sent") is not False
        ):
            raise ValueError("hourly research generic supersession bridge mismatch")
        return bridge

    @staticmethod
    def _transform_validation_relative(
        archive_date: str,
        slot: str,
        mode: str,
        source_input_sha256: str,
        transformer_identity_sha256: str,
    ) -> str:
        validation_key = _sha256(
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

    @staticmethod
    def _receipt(
        payload: Mapping[str, Any], digest: str, *, slot: str, mode: str
    ) -> dict[str, Any]:
        archive_date = str(payload["archive_date"])
        return {
            "schema_version": "v3_5.hourly_research_receipt.v1",
            "archive_date": archive_date,
            "slot": slot,
            "mode": mode,
            "payload_path": HourlyResearchStore._relative(
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

    @staticmethod
    def _transform_validation(
        payload: Mapping[str, Any],
        digest: str,
        *,
        slot: str,
        mode: str,
        transformer_identity_sha256: str,
    ) -> dict[str, Any]:
        archive_date = str(payload["archive_date"])
        source_input_sha256 = str(payload["source_input_sha256"])
        return {
            "schema_version": "v3_5.hourly_research_transform_validation.v1",
            "archive_date": archive_date,
            "slot": slot,
            "mode": mode,
            "payload_path": HourlyResearchStore._relative(
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

    def publish(
        self,
        payload: Mapping[str, Any],
        *,
        slot: str,
        mode: str,
        transformer_identity_sha256: str | None = None,
    ) -> dict[str, Any]:
        archive_date = validate_research_archive(payload)
        normalized_slot = _slot(slot)
        normalized_mode = str(mode).upper()
        if normalized_mode not in _MODES:
            raise ValueError(
                "hourly research mode must be LIVE, REPLAY, or BACKFILL"
            )
        normalized_transformer_sha = None
        if transformer_identity_sha256 is not None:
            normalized_transformer_sha = str(
                transformer_identity_sha256
            ).lower()
            if not _SHA256.fullmatch(normalized_transformer_sha):
                raise ValueError(
                    "hourly research transformer identity must be SHA-256"
                )
        relative = self._relative(
            archive_date, normalized_slot, normalized_mode
        )
        receipt_relative = self._receipt_relative(
            archive_date, normalized_slot, normalized_mode
        )
        digest = _sha256(payload)
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
                raise ValueError("conflicting hourly research materialization")
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
                    or _sha256(self._read(relative)) != digest
                    or not receipt_path.is_file()
                    or self._read(receipt_relative) != receipt
                ):
                    raise ValueError("hourly research integrity mismatch")
            elif payload_path.exists():
                if (
                    not payload_path.is_file()
                    or _sha256(self._read(relative)) != digest
                ):
                    raise ValueError(
                        "conflicting interrupted hourly research artifact"
                    )
                if receipt_path.exists():
                    if (
                        not receipt_path.is_file()
                        or self._read(receipt_relative) != receipt
                    ):
                        raise ValueError(
                            "conflicting interrupted hourly research receipt"
                        )
                else:
                    self._write(receipt_relative, receipt)
                manifest[relative] = digest
                self._write_manifest(manifest)
            else:
                if receipt_path.exists():
                    raise ValueError("orphan hourly research receipt")
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

    def replace(
        self,
        payload: Mapping[str, Any],
        *,
        slot: str,
        mode: str,
        expected_sha256: str,
        reason: str,
        transformer_identity_sha256: str | None = None,
        expected_source_sha256: str | None = None,
        source_provenance: Mapping[str, Any] | None = None,
        natural_execution_verified: bool = False,
    ) -> dict[str, Any]:
        """CAS-replace one exact hourly artifact while preserving its preimage.

        The canonical slot remains immutable unless the manifest and payload
        both match ``expected_sha256``.  The old payload/receipt are copied to
        a content-addressed history path before the canonical files change;
        the supersession receipt records the previous manifest/latest state.
        """

        archive_date = validate_research_archive(payload)
        normalized_slot = _slot(slot)
        normalized_mode = str(mode).upper()
        if normalized_mode not in _MODES:
            raise ValueError(
                "hourly research mode must be LIVE, REPLAY, or BACKFILL"
            )
        expected = str(expected_sha256 or "").strip().lower()
        if not _SHA256.fullmatch(expected):
            raise ValueError("hourly research expected SHA must be SHA-256")
        normalized_reason = str(reason or "").strip()
        if not normalized_reason:
            raise ValueError("hourly research replacement reason is required")
        normalized_transformer_sha = None
        if transformer_identity_sha256 is not None:
            normalized_transformer_sha = str(transformer_identity_sha256).lower()
            if not _SHA256.fullmatch(normalized_transformer_sha):
                raise ValueError(
                    "hourly research transformer identity must be SHA-256"
                )
        normalized_expected_source = None
        if expected_source_sha256 is not None:
            normalized_expected_source = str(expected_source_sha256).lower()
            if not _SHA256.fullmatch(normalized_expected_source):
                raise ValueError(
                    "hourly research expected source SHA must be SHA-256"
                )
        provenance = dict(source_provenance or {})
        recovery_info: dict[str, Any] | None = None
        if source_provenance is not None:
            if not isinstance(source_provenance, Mapping):
                raise ValueError("hourly research source provenance is invalid")
            if provenance.get("trade_date") not in {None, archive_date}:
                raise ValueError("hourly research source provenance date mismatch")
            if provenance.get("slot") not in {None, normalized_slot}:
                raise ValueError("hourly research source provenance slot mismatch")
            if provenance.get("source_input_sha256") not in {
                None,
                str(payload.get("source_input_sha256") or "").lower(),
            }:
                raise ValueError("hourly research source provenance SHA mismatch")
            json.dumps(provenance, ensure_ascii=False, sort_keys=True)
        if normalized_reason == "VERIFIED_LATE_SOURCE_RECOVERY":
            if natural_execution_verified:
                raise ValueError("late hourly recovery cannot claim natural execution")
            if not _SHA256.fullmatch(str(normalized_expected_source or "")):
                raise ValueError("hourly research recovery expected source SHA is required")
            if not isinstance(source_provenance, Mapping):
                raise ValueError("hourly research recovery provenance is required")
            recovery_metadata = provenance.get("recovery_metadata")
            source_manifest = provenance.get("source_manifest")
            if not isinstance(recovery_metadata, Mapping) or not isinstance(
                source_manifest, Mapping
            ):
                raise ValueError("hourly research recovery provenance is invalid")
            source_input_sha = str(provenance.get("source_input_sha256") or "").lower()
            if not _SHA256.fullmatch(source_input_sha) or source_input_sha != str(
                payload.get("source_input_sha256") or ""
            ).lower():
                raise ValueError("hourly research source provenance SHA mismatch")
            if (
                provenance.get("trade_date") != archive_date
                or provenance.get("slot") != normalized_slot
                or provenance.get("capture_origin") != "LATE_RECOVERY"
                or provenance.get("natural_execution_verified") is not False
                or (
                    "original_time_capture" in provenance
                    and provenance.get("original_time_capture") is not False
                )
                or provenance.get("supersedes_source_sha256")
                != normalized_expected_source
                or provenance.get("original_source_path")
                != recovery_metadata.get("original_source_path")
                or provenance.get("original_source_sha256")
                != recovery_metadata.get("original_source_sha256")
                or provenance.get("source_receipts")
                != source_manifest.get("source_receipts")
                or provenance.get("repair_authorization")
                != recovery_metadata.get("repair_authorization")
            ):
                raise ValueError("hourly research recovery provenance is invalid")
            receipts = source_manifest.get("source_receipts")
            recovery_path = _resolve_hourly_recovery_path(
                self.root, provenance.get("source_path"), field="source_path"
            )
            try:
                source_document = json.loads(
                    recovery_path.read_text(encoding="utf-8-sig")
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("hourly research recovery source payload is invalid") from error
            if not isinstance(source_document, Mapping):
                raise ValueError("hourly research recovery source payload is invalid")
            source_has_cannot_confirm = "cannot_confirm" in source_document
            supplied_has_cannot_confirm = "cannot_confirm" in provenance
            if source_has_cannot_confirm != supplied_has_cannot_confirm:
                # The runner historically projects an omitted optional field
                # through ``Mapping.get`` as null. Normalize only that one
                # source-absent/null case; a non-null fabricated value still
                # fails the source projection check below.
                if (
                    not source_has_cannot_confirm
                    and supplied_has_cannot_confirm
                    and provenance.get("cannot_confirm") is None
                ):
                    provenance.pop("cannot_confirm", None)
                else:
                    raise ValueError(
                        "hourly research recovery structured provenance mismatch"
                    )
            if (
                "original_time_capture" in provenance
                and provenance.get("original_time_capture")
                != source_document.get("original_time_capture")
            ):
                raise ValueError("hourly research recovery provenance is invalid")
            recovery_payload = {
                "recovery": True,
                "trade_date": archive_date,
                "slot": normalized_slot,
                "source_path": recovery_metadata.get("original_source_path"),
                "original_source_path": recovery_metadata.get("original_source_path"),
                "original_source_sha256": recovery_metadata.get(
                    "original_source_sha256"
                ),
                "supersedes": recovery_metadata.get("supersedes"),
                "retry_of_sha256": recovery_metadata.get("retry_of_sha256"),
                "pit_cutoff": source_manifest.get("pit_cutoff"),
                "capture_origin": "LATE_RECOVERY",
                "original_time_capture": False,
                "natural_execution_verified": False,
                "source_receipts": receipts,
                "source_manifest": dict(source_manifest),
                "recovery_metadata": dict(recovery_metadata),
                "repair_authorization": provenance.get("repair_authorization"),
            }
            # ``cannot_confirm`` is optional in the collector's recovery
            # document. Preserve whether the source omitted it or supplied an
            # explicit null/list so the direct CAS projection has the same
            # shape as the validated source object.
            if "cannot_confirm" in provenance:
                recovery_payload["cannot_confirm"] = provenance["cannot_confirm"]
            recovery_info = validate_hourly_recovery_provenance(
                data_root=self.root,
                archive_date=archive_date,
                slot=normalized_slot,
                recovery_path=recovery_path,
                recovery_sha256=source_input_sha,
                recovery_payload=recovery_payload,
                expected_source_sha256=normalized_expected_source,
                require_explicit_authorization=not _has_late_recovery_gap(
                    recovery_payload.get("cannot_confirm")
                ),
            )
        elif normalized_reason and natural_execution_verified:
            raise ValueError("late hourly recovery cannot claim natural execution")

        relative = self._relative(archive_date, normalized_slot, normalized_mode)
        receipt_relative = self._receipt_relative(
            archive_date, normalized_slot, normalized_mode
        )
        digest = _sha256(payload)
        replacement_receipt = self._receipt(
            payload,
            digest,
            slot=normalized_slot,
            mode=normalized_mode,
        )
        history_relative = self._history_relative(
            archive_date, normalized_slot, normalized_mode, expected
        )
        history_receipt_relative = self._history_receipt_relative(
            archive_date, normalized_slot, normalized_mode, expected
        )
        supersession_relative = self._supersession_relative(
            archive_date, normalized_slot, normalized_mode, digest
        )

        def _result(*, replaced: bool, latest_updated: bool, previous_source: str = "") -> dict[str, Any]:
            return {
                "archive_date": archive_date,
                "slot": normalized_slot,
                "mode": normalized_mode,
                "payload_path": relative,
                "receipt_path": receipt_relative,
                "payload_sha256": digest,
                "replaced": replaced,
                "previous_payload_path": history_relative if replaced or previous_source else "",
                "previous_receipt_path": history_receipt_relative if replaced or previous_source else "",
                "supersession_receipt_path": supersession_relative if replaced or previous_source else "",
                "latest_updated": latest_updated,
                "execution_origin": provenance.get("capture_origin", "REPLACEMENT"),
                "natural_execution_verified": bool(natural_execution_verified),
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }

        def _restore_raw(path: Path, existed: bool, raw: bytes | None) -> None:
            if existed and raw is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            elif not existed:
                path.unlink(missing_ok=True)

        with self._lock():
            manifest = self._manifest()
            current_digest = manifest.get(relative)
            payload_path = self._path(relative)
            receipt_path = self._path(receipt_relative)

            # Repeating the same repair is a verified no-op.  The caller can
            # retain the original expected SHA, while the current manifest
            # already points at the repaired payload.
            if current_digest == digest:
                if not payload_path.is_file() or not receipt_path.is_file():
                    raise ValueError("hourly research replacement artifact is incomplete")
                current_payload = self._read(relative)
                current_receipt = self._read(receipt_relative)
                if (
                    _sha256(current_payload) != digest
                    or validate_research_archive(current_payload) != archive_date
                    or current_receipt != self._receipt(
                        current_payload,
                        digest,
                        slot=normalized_slot,
                        mode=normalized_mode,
                    )
                ):
                    raise ValueError("hourly research replacement integrity mismatch")
                supersession_path = self._path(supersession_relative)
                if not supersession_path.is_file():
                    if expected != digest:
                        raise ValueError("hourly research supersession receipt is missing")
                    previous_source = str(
                        current_payload.get("source_input_sha256") or ""
                    ).lower()
                    if (
                        normalized_expected_source is not None
                        and previous_source != normalized_expected_source
                    ):
                        raise ValueError("hourly research expected source SHA mismatch")
                    if normalized_transformer_sha is not None:
                        self._publish_transform_validation_locked(
                            current_payload,
                            digest,
                            slot=normalized_slot,
                            mode=normalized_mode,
                            transformer_identity_sha256=normalized_transformer_sha,
                        )
                    return _result(replaced=False, latest_updated=False)
                supersession = self._read(supersession_relative)
                if not isinstance(supersession, Mapping):
                    raise ValueError("hourly research supersession receipt is invalid")
                previous_digest = str(
                    supersession.get("previous_payload_sha256") or ""
                ).lower()
                if (
                    not _SHA256.fullmatch(previous_digest)
                    or previous_digest == digest
                    or expected not in {previous_digest, digest}
                    or supersession.get("payload_sha256") != digest
                ):
                    raise ValueError("hourly research replacement expected SHA mismatch")
                history_relative = self._history_relative(
                    archive_date,
                    normalized_slot,
                    normalized_mode,
                    previous_digest,
                )
                history_receipt_relative = self._history_receipt_relative(
                    archive_date,
                    normalized_slot,
                    normalized_mode,
                    previous_digest,
                )
                history_path = self._path(history_relative)
                history_receipt_path = self._path(history_receipt_relative)
                if not history_path.is_file() or not history_receipt_path.is_file():
                    raise ValueError("hourly research replacement history is incomplete")
                previous_payload = self._read(history_relative)
                previous_receipt = self._read(history_receipt_relative)
                previous_source = str(
                    previous_payload.get("source_input_sha256") or ""
                ).lower()
                previous_latest = supersession.get("previous_latest_pointer")
                if previous_latest is not None:
                    self._validate_pointer(previous_latest)
                previous_manifest = self._previous_manifest_for_recovery(
                    self._manifest(),
                    archive_date=archive_date,
                    relative=relative,
                    previous_digest=previous_digest,
                    expected_sha256=str(
                        supersession.get("previous_manifest_sha256") or ""
                    ),
                    previous_latest=previous_latest,
                    expected_reason=normalized_reason,
                    expected_source_provenance=provenance,
                )
                latest_relative = "research/hourly/latest.json"
                latest_path = self._path(latest_relative)
                latest_current = None
                if latest_path.exists():
                    if not latest_path.is_file():
                        raise ValueError("hourly research latest pointer is invalid")
                    latest_current = self._read(latest_relative)
                    self._validate_pointer(latest_current)
                previous_latest_sha = (
                    _sha256(previous_latest) if previous_latest is not None else ""
                )
                if normalized_mode == "LIVE":
                    self._validate_hourly_latest_proof(
                        self._manifest(),
                        archive_date=archive_date,
                        slot=normalized_slot,
                        current_digest=digest,
                        previous_digest=previous_digest,
                        previous_manifest=previous_manifest,
                        previous_latest=previous_latest,
                        latest_current=latest_current,
                    )
                elif latest_current != previous_latest:
                    raise ValueError(
                        "hourly research previous latest pointer mismatch"
                    )
                if (
                    _sha256(previous_payload) != previous_digest
                    or validate_research_archive(previous_payload) != archive_date
                    or previous_receipt
                    != self._receipt(
                        previous_payload,
                        previous_digest,
                        slot=normalized_slot,
                        mode=normalized_mode,
                    )
                    or supersession.get("previous_receipt_sha256")
                    != _sha256(previous_receipt)
                    or supersession.get("schema_version")
                    != "v3_5.hourly_research_supersession.v1"
                    or supersession.get("archive_date") != archive_date
                    or supersession.get("slot") != normalized_slot
                    or supersession.get("mode") != normalized_mode
                    or supersession.get("payload_path") != relative
                    or supersession.get("payload_sha256") != digest
                    or supersession.get("source_input_sha256")
                    != str(payload.get("source_input_sha256") or "")
                    or supersession.get("previous_source_input_sha256")
                    != previous_source
                    or supersession.get("previous_payload_path") != history_relative
                    or supersession.get("previous_receipt_path")
                    != history_receipt_relative
                    or supersession.get("previous_manifest_sha256")
                    != _sha256(previous_manifest)
                    or supersession.get("previous_latest_pointer_sha256")
                    != previous_latest_sha
                    or supersession.get("reason") != normalized_reason
                    or supersession.get("transformer_identity_sha256")
                    != (normalized_transformer_sha or "")
                    or supersession.get("source_provenance") != provenance
                    or supersession.get("natural_execution_verified")
                    is not bool(natural_execution_verified)
                    or supersession.get("write_policy") != "read_only"
                    or supersession.get("production_allowed") is not False
                    or supersession.get("buy_gate_updated") is not False
                    or supersession.get("orders_sent") is not False
                ):
                    raise ValueError("hourly research replacement supersession mismatch")
                latest_updated = False
                if normalized_mode == "LIVE" and not self._latest_is_after(
                    archive_date, normalized_slot
                ):
                    latest_updated = self._update_latest(
                        archive_date, normalized_slot, digest
                    )
                return _result(
                    replaced=False,
                    latest_updated=latest_updated,
                    previous_source=str(supersession.get("previous_source_input_sha256") or ""),
                )

            if current_digest != expected:
                raise ValueError("hourly research expected SHA mismatch")
            if not payload_path.is_file() or not receipt_path.is_file():
                raise ValueError("hourly research replacement source is incomplete")

            previous_payload = self._read(relative)
            previous_receipt = self._read(receipt_relative)
            previous_digest = _sha256(previous_payload)
            if (
                previous_digest != expected
                or previous_receipt
                != self._receipt(
                    previous_payload,
                    previous_digest,
                    slot=normalized_slot,
                    mode=normalized_mode,
                )
                or validate_research_archive(previous_payload) != archive_date
            ):
                raise ValueError("hourly research replacement integrity mismatch")
            previous_source = str(previous_payload.get("source_input_sha256") or "").lower()
            if normalized_expected_source is not None and previous_source != normalized_expected_source:
                raise ValueError("hourly research expected source SHA mismatch")
            if digest == previous_digest:
                if normalized_transformer_sha is not None:
                    self._publish_transform_validation_locked(
                        payload,
                        digest,
                        slot=normalized_slot,
                        mode=normalized_mode,
                        transformer_identity_sha256=normalized_transformer_sha,
                    )
                return _result(replaced=False, latest_updated=False)

            latest_relative = "research/hourly/latest.json"
            latest_path = self._path(latest_relative)
            latest_existed = latest_path.is_file()
            latest_raw = latest_path.read_bytes() if latest_existed else None
            latest_before = self._read(latest_relative) if latest_existed else None
            if latest_existed:
                self._validate_pointer(latest_before)
                latest_position = (
                    str(latest_before["archive_date"]),
                    str(latest_before["slot"]),
                )
                requested_position = (archive_date, normalized_slot)
                if latest_position == requested_position and latest_before["payload_sha256"] != expected:
                    raise ValueError("hourly research latest pointer target mismatch")

            history_path = self._path(history_relative)
            history_receipt_path = self._path(history_receipt_relative)
            supersession_path = self._path(supersession_relative)
            history_payload = previous_payload
            history_receipt = previous_receipt
            if history_path.exists() and (
                not history_path.is_file() or self._read(history_relative) != history_payload
            ):
                raise ValueError("hourly research history conflict")
            if history_receipt_path.exists() and (
                not history_receipt_path.is_file()
                or self._read(history_receipt_relative) != history_receipt
            ):
                raise ValueError("hourly research history receipt conflict")
            supersession = {
                "schema_version": "v3_5.hourly_research_supersession.v1",
                "archive_date": archive_date,
                "slot": normalized_slot,
                "mode": normalized_mode,
                "payload_path": relative,
                "payload_sha256": digest,
                "source_input_sha256": str(payload.get("source_input_sha256") or ""),
                "previous_payload_path": history_relative,
                "previous_payload_sha256": previous_digest,
                "previous_receipt_path": history_receipt_relative,
                "previous_receipt_sha256": _sha256(previous_receipt),
                "previous_source_input_sha256": previous_source,
                "reason": normalized_reason,
                "transformer_identity_sha256": normalized_transformer_sha or "",
                "source_provenance": provenance,
                "natural_execution_verified": bool(natural_execution_verified),
                "previous_manifest_sha256": _sha256(manifest),
                "previous_latest_pointer": latest_before,
                "previous_latest_pointer_sha256": _sha256(latest_before) if latest_before is not None else "",
                "write_policy": "read_only",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
            if supersession_path.exists() and (
                not supersession_path.is_file()
                or self._read(supersession_relative) != supersession
            ):
                raise ValueError("hourly research supersession conflict")

            manifest_path = self._path("manifest.json")
            manifest_existed = manifest_path.is_file()
            manifest_raw = manifest_path.read_bytes() if manifest_existed else None
            payload_raw = payload_path.read_bytes()
            receipt_raw = receipt_path.read_bytes()
            validation_relative = (
                self._transform_validation_relative(
                    archive_date,
                    normalized_slot,
                    normalized_mode,
                    str(payload.get("source_input_sha256") or "").lower(),
                    normalized_transformer_sha,
                )
                if normalized_transformer_sha is not None
                else None
            )
            validation_path = self._path(validation_relative) if validation_relative else None
            validation_existed = bool(validation_path and validation_path.is_file())
            validation_raw = validation_path.read_bytes() if validation_existed and validation_path else None

            latest_updated = False
            try:
                if not history_path.exists():
                    self._write(history_relative, history_payload)
                if not history_receipt_path.exists():
                    self._write(history_receipt_relative, history_receipt)
                if not supersession_path.exists():
                    self._write(supersession_relative, supersession)
                if normalized_transformer_sha is not None:
                    self._publish_transform_validation_locked(
                        payload,
                        digest,
                        slot=normalized_slot,
                        mode=normalized_mode,
                        transformer_identity_sha256=normalized_transformer_sha,
                    )
                self._write(relative, payload)
                self._write(receipt_relative, replacement_receipt)
                manifest[relative] = digest
                self._write_manifest(manifest)
                if normalized_mode == "LIVE" and not self._latest_is_after(
                    archive_date, normalized_slot
                ):
                    latest_updated = self._update_latest(
                        archive_date, normalized_slot, digest
                    )
            except Exception:
                # Canonical files are restored through the base atomic writer,
                # bypassing an injected subclass failure.  History remains as
                # evidence, while the live manifest/latest view is unchanged.
                _restore_raw(payload_path, True, payload_raw)
                _restore_raw(receipt_path, True, receipt_raw)
                _restore_raw(manifest_path, manifest_existed, manifest_raw)
                _restore_raw(latest_path, latest_existed, latest_raw)
                if validation_path is not None:
                    _restore_raw(validation_path, validation_existed, validation_raw)
                raise

        return _result(
            replaced=True,
            latest_updated=latest_updated,
            previous_source=previous_source,
        )

    def verify_recovery_replacement(
        self,
        payload: Mapping[str, Any],
        *,
        slot: str,
        mode: str,
        current_source_sha256: str,
        previous_source_sha256: str,
        reason: str,
        transformer_identity_sha256: str | None,
        source_provenance: Mapping[str, Any] | None,
        natural_execution_verified: bool = False,
    ) -> dict[str, str]:
        """Verify an already-committed late recovery and return its preimage.

        A retry after the hourly CAS has committed must prove the current
        payload, receipt, content-addressed history, and supersession receipt
        before it can continue to the generic archive CAS.  This method is
        read-only; it intentionally fails closed on any missing or conflicting
        evidence.
        """

        archive_date = validate_research_archive(payload)
        normalized_slot = _slot(slot)
        normalized_mode = str(mode).upper()
        if normalized_mode not in _MODES:
            raise ValueError(
                "hourly research mode must be LIVE, REPLAY, or BACKFILL"
            )
        normalized_reason = str(reason or "").strip()
        if not normalized_reason:
            raise ValueError("hourly research recovery reason is required")
        normalized_transformer_sha = None
        if transformer_identity_sha256 is not None:
            normalized_transformer_sha = str(transformer_identity_sha256).lower()
            if not _SHA256.fullmatch(normalized_transformer_sha):
                raise ValueError(
                    "hourly research recovery transformer identity is invalid"
                )
        if source_provenance is not None and not isinstance(
            source_provenance, Mapping
        ):
            raise ValueError("hourly research recovery source provenance is invalid")
        provenance = dict(source_provenance or {})
        try:
            json.dumps(provenance, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "hourly research recovery source provenance is invalid"
            ) from error
        if natural_execution_verified:
            raise ValueError("hourly research recovery cannot claim natural execution")
        current_source = str(current_source_sha256 or "").lower()
        previous_source = str(previous_source_sha256 or "").lower()
        if not _SHA256.fullmatch(current_source):
            raise ValueError("hourly research recovery current source SHA is invalid")
        if not _SHA256.fullmatch(previous_source):
            raise ValueError("hourly research recovery previous source SHA is invalid")
        if str(payload.get("source_input_sha256") or "").lower() != current_source:
            raise ValueError("hourly research recovery current source SHA mismatch")

        relative = self._relative(archive_date, normalized_slot, normalized_mode)
        supersession_relative = self._supersession_relative(
            archive_date,
            normalized_slot,
            normalized_mode,
            _sha256(payload),
        )
        with self._lock():
            current = self.read_exact(
                archive_date,
                normalized_slot,
                mode=normalized_mode,
            )
            if current is None or current != dict(payload):
                raise ValueError("hourly research recovery replacement payload mismatch")
            current_digest = _sha256(current)
            manifest = self._manifest()
            if manifest.get(relative) != current_digest:
                raise ValueError("hourly research recovery manifest mismatch")
            supersession_path = self._path(supersession_relative)
            if not supersession_path.is_file():
                raise ValueError("hourly research supersession receipt is missing")
            supersession = self._read(supersession_relative)
            if not isinstance(supersession, Mapping):
                raise ValueError("hourly research supersession receipt is invalid")
            previous_digest = str(
                supersession.get("previous_payload_sha256") or ""
            ).lower()
            previous_latest = supersession.get("previous_latest_pointer")
            if previous_latest is not None:
                self._validate_pointer(previous_latest)
            history_relative = self._history_relative(
                archive_date,
                normalized_slot,
                normalized_mode,
                previous_digest,
            )
            history_receipt_relative = self._history_receipt_relative(
                archive_date,
                normalized_slot,
                normalized_mode,
                previous_digest,
            )
            previous_manifest = self._previous_manifest_for_recovery(
                manifest,
                archive_date=archive_date,
                relative=relative,
                previous_digest=previous_digest,
                expected_sha256=str(
                    supersession.get("previous_manifest_sha256") or ""
                ),
                previous_latest=previous_latest,
                expected_reason=normalized_reason,
                expected_source_provenance=provenance,
            )
            latest_relative = "research/hourly/latest.json"
            latest_path = self._path(latest_relative)
            latest_current = None
            if latest_path.exists():
                if not latest_path.is_file():
                    raise ValueError("hourly research latest pointer is invalid")
                latest_current = self._read(latest_relative)
                self._validate_pointer(latest_current)
            previous_latest_sha = (
                _sha256(previous_latest) if previous_latest is not None else ""
            )
            if normalized_mode == "LIVE":
                self._validate_hourly_latest_proof(
                    manifest,
                    archive_date=archive_date,
                    slot=normalized_slot,
                    current_digest=current_digest,
                    previous_digest=previous_digest,
                    previous_manifest=previous_manifest,
                    previous_latest=previous_latest,
                    latest_current=latest_current,
                )
            elif latest_current != previous_latest:
                raise ValueError(
                    "hourly research previous latest pointer mismatch"
                )
            if (
                supersession.get("schema_version")
                != "v3_5.hourly_research_supersession.v1"
                or supersession.get("archive_date") != archive_date
                or supersession.get("slot") != normalized_slot
                or supersession.get("mode") != normalized_mode
                or supersession.get("payload_path") != relative
                or supersession.get("payload_sha256") != current_digest
                or supersession.get("source_input_sha256")
                != str(current.get("source_input_sha256") or "")
                or not _SHA256.fullmatch(previous_digest)
                or supersession.get("previous_source_input_sha256")
                != previous_source
                or supersession.get("previous_payload_path") != history_relative
                or supersession.get("previous_receipt_path")
                != history_receipt_relative
                or supersession.get("previous_manifest_sha256")
                != _sha256(previous_manifest)
                or supersession.get("previous_latest_pointer_sha256")
                != previous_latest_sha
                or supersession.get("reason") != normalized_reason
                or supersession.get("transformer_identity_sha256")
                != (normalized_transformer_sha or "")
                or supersession.get("source_provenance") != provenance
                or supersession.get("natural_execution_verified")
                is not bool(natural_execution_verified)
                or supersession.get("write_policy") != "read_only"
                or supersession.get("production_allowed") is not False
                or supersession.get("buy_gate_updated") is not False
                or supersession.get("orders_sent") is not False
            ):
                raise ValueError("hourly research supersession receipt mismatch")
            history_path = self._path(history_relative)
            history_receipt_path = self._path(history_receipt_relative)
            if not history_path.is_file() or not history_receipt_path.is_file():
                raise ValueError("hourly research replacement history is incomplete")
            previous_payload = self._read(history_relative)
            previous_receipt = self._read(history_receipt_relative)
            if (
                _sha256(previous_payload) != previous_digest
                or validate_research_archive(previous_payload) != archive_date
                or previous_receipt
                != self._receipt(
                    previous_payload,
                    previous_digest,
                    slot=normalized_slot,
                    mode=normalized_mode,
                )
                or supersession.get("previous_receipt_sha256")
                != _sha256(previous_receipt)
            ):
                raise ValueError("hourly research replacement history mismatch")
            return {
                "payload_sha256": current_digest,
                "previous_payload_sha256": previous_digest,
                "previous_payload_path": history_relative,
                "previous_receipt_path": history_receipt_relative,
                "supersession_receipt_path": supersession_relative,
            }

    def _publish_transform_validation_locked(
        self,
        payload: Mapping[str, Any],
        digest: str,
        *,
        slot: str,
        mode: str,
        transformer_identity_sha256: str,
    ) -> None:
        archive_date = str(payload["archive_date"])
        source_input_sha256 = str(payload["source_input_sha256"]).lower()
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
                raise ValueError(
                    "hourly research transform validation mismatch"
                )
        else:
            self._write(validation_relative, validation)

    def _assert_latest_not_backwards(
        self, archive_date: str, slot: str
    ) -> None:
        if self._latest_is_after(archive_date, slot):
            raise ValueError(
                "LIVE hourly research publication cannot move latest backwards"
            )

    def _latest_is_after(self, archive_date: str, slot: str) -> bool:
        destination = self._path("research/hourly/latest.json")
        if not destination.exists():
            return False
        if not destination.is_file():
            raise ValueError("invalid hourly research latest pointer")
        existing = self._read("research/hourly/latest.json")
        self._validate_pointer(existing)
        return (
            str(existing["archive_date"]),
            str(existing["slot"]),
        ) > (archive_date, slot)

    def _update_latest(
        self, archive_date: str, slot: str, digest: str
    ) -> bool:
        relative = "research/hourly/latest.json"
        destination = self._path(relative)
        if destination.is_file():
            existing = self._read(relative)
            self._validate_pointer(existing)
            existing_position = (
                str(existing["archive_date"]),
                str(existing["slot"]),
            )
            requested_position = (archive_date, slot)
            if existing_position > requested_position:
                raise ValueError(
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
        pointer = {**body, "pointer_semantic_hash": _sha256(body)}
        self._write(relative, pointer)
        return True

    @staticmethod
    def _latest_pointer(
        archive_date: str, slot: str, digest: str
    ) -> dict[str, Any]:
        body = {
            "schema_version": "v3_5.hourly_research_latest_pointer.v1",
            "archive_date": archive_date,
            "slot": slot,
            "mode": "LIVE",
            "payload_path": HourlyResearchStore._relative(
                archive_date, slot, "LIVE"
            ),
            "payload_sha256": digest,
        }
        return {**body, "pointer_semantic_hash": _sha256(body)}

    @staticmethod
    def _validate_pointer(pointer: Mapping[str, Any]) -> None:
        fields = {
            "schema_version",
            "archive_date",
            "slot",
            "mode",
            "payload_path",
            "payload_sha256",
            "pointer_semantic_hash",
        }
        if not isinstance(pointer, Mapping) or set(pointer) != fields:
            raise ValueError("invalid hourly research latest pointer")
        archive_date = _date(str(pointer.get("archive_date") or ""))
        slot = _slot(str(pointer.get("slot") or ""))
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
            != HourlyResearchStore._relative(archive_date, slot, "LIVE")
            or not _SHA256.fullmatch(str(pointer.get("payload_sha256") or ""))
            or pointer.get("pointer_semantic_hash") != _sha256(body)
        ):
            raise ValueError("invalid hourly research latest pointer")

    def list_slots(self, archive_date: str, *, mode: str) -> list[str]:
        """Return verified slots for one exact archive date.

        Date-bound consumers must enumerate the manifest and both on-disk
        sides before reading a slot.  In particular, this method never falls
        back to the LIVE latest pointer, which could silently cross a date
        boundary during next-day materialization.
        """

        archive_date = _date(archive_date)
        normalized_mode = str(mode).upper()
        if normalized_mode not in _MODES:
            raise ValueError(
                "hourly research mode must be LIVE, REPLAY, or BACKFILL"
            )
        mode_dir = normalized_mode.lower()
        artifact_prefix = f"research/hourly/{mode_dir}/{archive_date}/"
        receipt_prefix = f"receipts/research/hourly/{mode_dir}/{archive_date}/"
        manifest = self._manifest()
        manifest_slots: set[str] = set()
        for relative in manifest:
            if not relative.startswith(artifact_prefix):
                continue
            suffix = relative[len(artifact_prefix) :]
            if "/" in suffix or not suffix.endswith(".json"):
                continue
            manifest_slots.add(_slot(suffix[:-5]))

        def file_slots(relative: str) -> set[str]:
            directory = self._path(relative)
            if not directory.exists():
                return set()
            if not directory.is_dir():
                raise ValueError(
                    "hourly research slot directory is not a directory"
                )
            slots: set[str] = set()
            for candidate in directory.iterdir():
                if not candidate.is_file() or candidate.suffix != ".json":
                    continue
                slots.add(_slot(candidate.stem))
            return slots

        artifact_slots = file_slots(artifact_prefix)
        receipt_slots = file_slots(receipt_prefix)
        if (
            manifest_slots != artifact_slots
            or manifest_slots != receipt_slots
        ):
            raise ValueError("hourly research manifest or receipt mismatch")

        verified: list[str] = []
        for slot in sorted(manifest_slots):
            if self.read_exact(archive_date, slot, mode=normalized_mode) is None:
                raise ValueError("hourly research manifest or receipt mismatch")
            verified.append(slot)
        return verified

    def read_latest_for_date(
        self, archive_date: str, *, mode: str
    ) -> tuple[str, dict[str, Any]] | None:
        """Read the highest verified slot for one exact date only."""

        archive_date = _date(archive_date)
        slots = self.list_slots(archive_date, mode=mode)
        if not slots:
            return None
        slot = slots[-1]
        payload = self.read_exact(archive_date, slot, mode=mode)
        if payload is None:
            raise ValueError("hourly research manifest or receipt mismatch")
        return slot, payload

    def read_exact(
        self, archive_date: str, slot: str, *, mode: str
    ) -> dict[str, Any] | None:
        archive_date = _date(archive_date)
        normalized_slot = _slot(slot)
        normalized_mode = str(mode).upper()
        if normalized_mode not in _MODES:
            raise ValueError(
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
                raise ValueError("hourly research manifest or receipt mismatch")
            return None
        payload = self._read(relative)
        digest = _sha256(payload)
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
            or validate_research_archive(payload) != archive_date
        ):
            raise ValueError("hourly research manifest or receipt mismatch")
        return payload

    def reuse_matching_source(
        self,
        archive_date: str,
        slot: str,
        *,
        mode: str,
        source_input_sha256: str,
        transformer_identity_sha256: str,
    ) -> dict[str, Any] | None:
        """Republish a finalized exact artifact only when its source is identical."""
        archive_date = _date(archive_date)
        normalized_slot = _slot(slot)
        normalized_mode = str(mode).upper()
        if normalized_mode not in _MODES:
            raise ValueError(
                "hourly research mode must be LIVE, REPLAY, or BACKFILL"
            )
        normalized_source_sha = str(source_input_sha256).lower()
        if not _SHA256.fullmatch(normalized_source_sha):
            raise ValueError("hourly research source SHA must be SHA-256")
        normalized_transformer_sha = str(transformer_identity_sha256).lower()
        if not _SHA256.fullmatch(normalized_transformer_sha):
            raise ValueError("hourly research transformer identity must be SHA-256")
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
                    raise ValueError(
                        "invalid hourly research transform validation"
                    )
                return None
            if relative not in self._manifest():
                raise ValueError("orphan hourly research transform validation")
            payload = self.read_exact(
                archive_date,
                normalized_slot,
                mode=normalized_mode,
            )
            if payload is None:
                raise ValueError("hourly research manifest or receipt mismatch")
            digest = _sha256(payload)
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
                raise ValueError(
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

    def read_latest(self) -> dict[str, Any] | None:
        relative = "research/hourly/latest.json"
        pointer_path = self._path(relative)
        if not pointer_path.is_file():
            if pointer_path.exists():
                raise ValueError("invalid hourly research latest pointer")
            return None
        pointer = self._read(relative)
        self._validate_pointer(pointer)
        payload = self.read_exact(
            str(pointer["archive_date"]),
            str(pointer["slot"]),
            mode="LIVE",
        )
        if payload is None or _sha256(payload) != pointer["payload_sha256"]:
            raise ValueError("hourly research latest pointer target mismatch")
        return payload

__all__ = ["HourlyResearchStore", "ResearchArchiveStore", "ResearchSelectionStore"]
