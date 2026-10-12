"""Shared hourly research archive store used by V4 runtime facades."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from contracts.research import validate_research_archive
from infrastructure.data_store import NativeDataStore, _date, _sha256
from infrastructure.owned_path import resolve_owned_path

_MODES = frozenset({"LIVE", "REPLAY", "BACKFILL"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _slot(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}", value):
        raise ValueError("research slot must use HHMM")
    if int(value[:2]) > 23 or int(value[2:]) > 59:
        raise ValueError("research slot must be a real time")
    return value


class HourlyResearchStore(NativeDataStore):
    """Immutable per-slot research artifacts with a LIVE-only latest pointer."""

    def _normalize_ready_empty_owned_path(
        self, value: str, expected_relative: str
    ) -> str:
        from infrastructure._research_store_parts.hourly_sources import (
            _HourlyResearchStore__normalize_ready_empty_owned_path_body as _v4_impl,
        )
        return _v4_impl(globals(), self, value, expected_relative)

    def _validate_ready_empty_source(
        self,
        payload: Mapping[str, Any],
        *,
        archive_date: str,
        slot: str,
        mode: str,
    ) -> None:
        from infrastructure._research_store_parts.hourly_sources import (
            _HourlyResearchStore__validate_ready_empty_source_body as _v4_impl,
        )
        return _v4_impl(
            globals(),
            self,
            payload,
            archive_date=archive_date,
            slot=slot,
            mode=mode,
        )

    def _path(self, relative: str) -> Path:
        return resolve_owned_path(self.root, relative)

    @staticmethod
    def _relative(archive_date: str, slot: str, mode: str) -> str:
        return f"research/hourly/{mode.lower()}/{archive_date}/{slot}.json"

    @staticmethod
    def _receipt_relative(archive_date: str, slot: str, mode: str) -> str:
        return f"receipts/research/hourly/{mode.lower()}/{archive_date}/{slot}.json"

    @staticmethod
    def _transform_validation_relative(
        archive_date: str,
        slot: str,
        mode: str,
        source_input_sha256: str,
        transformer_identity_sha256: str,
    ) -> str:
        from infrastructure._research_store_parts.hourly_publish import _HourlyResearchStore__transform_validation_relative_body as _v4_impl
        return _v4_impl(globals(), archive_date, slot, mode, source_input_sha256, transformer_identity_sha256)

    @staticmethod
    def _receipt(
        payload: Mapping[str, Any], digest: str, *, slot: str, mode: str
    ) -> dict[str, Any]:
        from infrastructure._research_store_parts.hourly_publish import _HourlyResearchStore__receipt_body as _v4_impl
        return _v4_impl(globals(), payload, digest, slot=slot, mode=mode)

    @staticmethod
    def _transform_validation(
        payload: Mapping[str, Any],
        digest: str,
        *,
        slot: str,
        mode: str,
        transformer_identity_sha256: str,
    ) -> dict[str, Any]:
        from infrastructure._research_store_parts.hourly_publish import _HourlyResearchStore__transform_validation_body as _v4_impl
        return _v4_impl(globals(), payload, digest, slot=slot, mode=mode, transformer_identity_sha256=transformer_identity_sha256)

    def publish(
        self,
        payload: Mapping[str, Any],
        *,
        slot: str,
        mode: str,
        transformer_identity_sha256: str | None = None,
    ) -> dict[str, Any]:
        from infrastructure._research_store_parts.hourly_publish import _HourlyResearchStore_publish_body as _v4_impl
        return _v4_impl(globals(), self, payload, slot=slot, mode=mode, transformer_identity_sha256=transformer_identity_sha256)

    def _publish_transform_validation_locked(
        self,
        payload: Mapping[str, Any],
        digest: str,
        *,
        slot: str,
        mode: str,
        transformer_identity_sha256: str,
    ) -> None:
        from infrastructure._research_store_parts.hourly_publish import _HourlyResearchStore__publish_transform_validation_locked_body as _v4_impl
        return _v4_impl(globals(), self, payload, digest, slot=slot, mode=mode, transformer_identity_sha256=transformer_identity_sha256)

    def _assert_latest_not_backwards(
        self, archive_date: str, slot: str
    ) -> None:
        if self._latest_is_after(archive_date, slot):
            raise ValueError(
                "LIVE hourly research publication cannot move latest backwards"
            )

    def _latest_is_after(self, archive_date: str, slot: str) -> bool:
        from infrastructure._research_store_parts.hourly_publish import _HourlyResearchStore__latest_is_after_body as _v4_impl
        return _v4_impl(globals(), self, archive_date, slot)

    def _update_latest(
        self, archive_date: str, slot: str, digest: str
    ) -> bool:
        from infrastructure._research_store_parts.hourly_publish import _HourlyResearchStore__update_latest_body as _v4_impl
        return _v4_impl(globals(), self, archive_date, slot, digest)

    @staticmethod
    def _validate_pointer(pointer: Mapping[str, Any]) -> None:
        from infrastructure._research_store_parts.hourly_publish import _HourlyResearchStore__validate_pointer_body as _v4_impl
        return _v4_impl(globals(), pointer)

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
        from infrastructure._research_store_parts.hourly_sources import _HourlyResearchStore_read_latest_for_date_body as _v4_impl
        return _v4_impl(globals(), self, archive_date, mode=mode)

    def read_exact(
        self, archive_date: str, slot: str, *, mode: str
    ) -> dict[str, Any] | None:
        from infrastructure._research_store_parts.hourly_sources import _HourlyResearchStore_read_exact_body as _v4_impl
        return _v4_impl(globals(), self, archive_date, slot, mode=mode)

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
        from infrastructure._research_store_parts.hourly_sources import _HourlyResearchStore_reuse_matching_source_body as _v4_impl
        return _v4_impl(globals(), self, archive_date, slot, mode=mode, source_input_sha256=source_input_sha256, transformer_identity_sha256=transformer_identity_sha256)

    def read_latest(self) -> dict[str, Any] | None:
        from infrastructure._research_store_parts.hourly_sources import _HourlyResearchStore_read_latest_body as _v4_impl
        return _v4_impl(globals(), self)

__all__ = ["HourlyResearchStore"]
