"""Strict Google Drive v3 byte-readback evidence helpers.

This module never authenticates on its own.  A transport (official Drive API or
an approved connector) must provide two independent metadata snapshots and the
raw downloaded bytes.  No self-declared ``uploaded=True`` field is accepted.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence


class DriveEvidenceError(ValueError):
    """Drive evidence is incomplete, inconsistent, late, or not byte-identical."""


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise DriveEvidenceError(f"Drive metadata missing {field}")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise DriveEvidenceError(f"invalid Drive {field}") from exc
    if parsed.tzinfo is None:
        raise DriveEvidenceError(f"Drive {field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _json_object(raw: bytes, label: str) -> Mapping[str, Any]:
    def pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise DriveEvidenceError(f"duplicate key in {label}")
            out[key] = value
        return out

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs_no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DriveEvidenceError(f"invalid {label} JSON") from exc
    if not isinstance(value, dict):
        raise DriveEvidenceError(f"{label} must be a JSON object")
    return value


def _mapping(value: bytes | Mapping[str, Any], label: str) -> Mapping[str, Any]:
    if isinstance(value, bytes):
        return _json_object(value, label)
    if isinstance(value, Mapping):
        return value
    raise DriveEvidenceError(f"{label} must be raw JSON bytes or an object")


def _revision_token(
    meta: Mapping[str, Any], revision_id: str | None, revision_source: str | None
) -> tuple[str, str]:
    # Drive File.version is a server-side monotonically increasing version. For
    # binary files Drive may also expose headRevisionId; a separately retrieved
    # revisions.list current revision is accepted when neither appears.
    for key in ("version", "headRevisionId"):
        value = meta.get(key)
        if value is not None and str(value):
            return str(value), f"files.get.{key}"
    if revision_id and revision_source == "drive.revisions.list.currentRevisionId":
        return revision_id, revision_source
    raise DriveEvidenceError(
        "Drive version identity missing: require files.get version/headRevisionId "
        "or a verified revisions.list currentRevisionId"
    )


@dataclass(frozen=True)
class DriveFileExpectation:
    file_id: str
    name: str
    parent_id: str
    mime_type: str
    sha256: str
    size_bytes: int
    expected_version: str | None = None
    created_not_after: datetime | None = None
    modified_not_after: datetime | None = None
    readback_not_after: datetime | None = None

    def __post_init__(self) -> None:
        if not self.file_id or not self.name or not self.parent_id or not self.mime_type:
            raise DriveEvidenceError("Drive file identity fields must be non-empty")
        if self.mime_type.startswith("application/vnd.google-apps."):
            raise DriveEvidenceError("native Google documents do not provide raw file bytes")
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise DriveEvidenceError("expected SHA256 must be lowercase hex")
        if self.size_bytes < 0:
            raise DriveEvidenceError("expected size cannot be negative")
        for name in ("created_not_after", "modified_not_after", "readback_not_after"):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise DriveEvidenceError(f"{name} must include a timezone")


@dataclass(frozen=True)
class VerifiedDriveReceipt:
    file_id: str
    name: str
    parent_ids: tuple[str, ...]
    mime_type: str
    version_token: str
    version_source: str
    size_bytes: int
    sha256: str
    created_time: datetime
    modified_time: datetime
    observed_at: datetime


def verify_google_drive_readback(
    before_metadata: bytes | Mapping[str, Any],
    downloaded_bytes: bytes,
    after_metadata: bytes | Mapping[str, Any],
    *,
    expected: DriveFileExpectation,
    observed_at: datetime,
    before_revision_id: str | None = None,
    after_revision_id: str | None = None,
    before_revision_source: str | None = None,
    after_revision_source: str | None = None,
) -> VerifiedDriveReceipt:
    """Verify a bracketed metadata/download/readback observation.

    ``before_metadata`` and ``after_metadata`` must be actual Drive API/approved
    connector responses, and ``downloaded_bytes`` must be returned media bytes.
    If the transport normalizes away Drive's native version fields, pass the
    current revision IDs obtained from ``revisions.list`` for both sides.
    """
    if not isinstance(downloaded_bytes, bytes):
        raise DriveEvidenceError("download must be actual bytes")
    if observed_at.tzinfo is None:
        raise DriveEvidenceError("readback observation time must include a timezone")
    before = _mapping(before_metadata, "before metadata")
    after = _mapping(after_metadata, "after metadata")

    def extract(meta: Mapping[str, Any], rev_id: str | None, rev_source: str | None):
        required = ("id", "name", "mimeType", "size", "createdTime", "modifiedTime", "parents")
        missing = [key for key in required if key not in meta]
        if missing:
            raise DriveEvidenceError("Drive metadata missing: " + ", ".join(missing))
        parents = meta["parents"]
        if not isinstance(parents, list) or not all(isinstance(x, str) and x for x in parents):
            raise DriveEvidenceError("Drive parents must be a string array")
        if len(set(parents)) != len(parents):
            raise DriveEvidenceError("Drive parents contain duplicates")
        size_raw = meta["size"]
        try:
            size = int(size_raw)
        except (TypeError, ValueError) as exc:
            raise DriveEvidenceError("Drive size is not an integer") from exc
        if size < 0 or str(size) != str(size_raw):
            raise DriveEvidenceError("Drive size is not a canonical non-negative integer")
        created = _parse_time(meta["createdTime"], "createdTime")
        modified = _parse_time(meta["modifiedTime"], "modifiedTime")
        version, version_source = _revision_token(meta, rev_id, rev_source)
        return {
            "id": str(meta["id"]),
            "name": str(meta["name"]),
            "mimeType": str(meta["mimeType"]),
            "size": size,
            "parents": tuple(sorted(parents)),
            "createdTime": created,
            "modifiedTime": modified,
            "version": version,
            "version_source": version_source,
            # Compare both native fields even when only one is the primary
            # token. A stable head revision does not hide a changed Drive
            # `version` value.
            "files_version": str(meta["version"]) if meta.get("version") is not None else None,
            "head_revision_id": str(meta["headRevisionId"]) if meta.get("headRevisionId") is not None else None,
        }

    before_values = extract(before, before_revision_id, before_revision_source)
    after_values = extract(after, after_revision_id, after_revision_source)
    if before_values != after_values:
        raise DriveEvidenceError("Drive file identity/version changed during readback")
    if before_values["id"] != expected.file_id:
        raise DriveEvidenceError("Drive file ID mismatch")
    if before_values["name"] != expected.name:
        raise DriveEvidenceError("Drive file name mismatch")
    if before_values["parents"] != (expected.parent_id,):
        raise DriveEvidenceError("Drive parent directory mismatch")
    if before_values["mimeType"] != expected.mime_type:
        raise DriveEvidenceError("Drive MIME type mismatch")
    if expected.expected_version is not None and before_values["version"] != expected.expected_version:
        raise DriveEvidenceError("Drive version does not match pinned version")
    if before_values["size"] != len(downloaded_bytes) or len(downloaded_bytes) != expected.size_bytes:
        raise DriveEvidenceError("Drive size does not match downloaded/original bytes")
    content_sha = sha256_bytes(downloaded_bytes)
    if content_sha != expected.sha256:
        raise DriveEvidenceError("Drive downloaded bytes SHA256 mismatch")

    observed = observed_at.astimezone(timezone.utc)
    created, modified = before_values["createdTime"], before_values["modifiedTime"]
    if modified < created:
        raise DriveEvidenceError("Drive modifiedTime predates createdTime")
    if observed < modified:
        raise DriveEvidenceError("Drive readback observation predates Drive modifiedTime")
    if expected.created_not_after and created > expected.created_not_after.astimezone(timezone.utc):
        raise DriveEvidenceError("Drive file was created after the permitted time")
    if expected.modified_not_after and modified > expected.modified_not_after.astimezone(timezone.utc):
        raise DriveEvidenceError("Drive file was modified after the permitted time")
    if expected.readback_not_after and observed > expected.readback_not_after.astimezone(timezone.utc):
        raise DriveEvidenceError("Drive readback occurred after the required deadline")

    return VerifiedDriveReceipt(
        file_id=before_values["id"],
        name=before_values["name"],
        parent_ids=before_values["parents"],
        mime_type=before_values["mimeType"],
        version_token=before_values["version"],
        version_source=before_values["version_source"],
        size_bytes=before_values["size"],
        sha256=content_sha,
        created_time=created,
        modified_time=modified,
        observed_at=observed,
    )


class DriveV3Transport(Protocol):
    """Minimal transport contract; credentials stay inside its implementation."""

    def get_file_metadata(self, file_id: str) -> Mapping[str, Any]: ...

    def list_revisions(self, file_id: str) -> Sequence[Mapping[str, Any]]: ...

    def download_media(self, file_id: str) -> bytes: ...

    def create_file(self, *, name: str, parent_id: str, mime_type: str, content: bytes) -> Mapping[str, Any]: ...


def _current_revision_id(revisions: Sequence[Mapping[str, Any]]) -> str:
    """Choose a unique latest revision; timestamp ties fail closed."""
    candidates: list[tuple[datetime, str]] = []
    for revision in revisions:
        revision_id = revision.get("id")
        modified = revision.get("modifiedTime")
        if isinstance(revision_id, str) and revision_id:
            candidates.append((_parse_time(modified, "revision.modifiedTime"), revision_id))
    if not candidates:
        raise DriveEvidenceError("Drive revisions.list returned no usable revision")
    candidates.sort(key=lambda item: item[0])
    latest_time = candidates[-1][0]
    latest_ids = {revision_id for time, revision_id in candidates if time == latest_time}
    if len(latest_ids) != 1:
        raise DriveEvidenceError("Drive latest revision is ambiguous")
    return next(iter(latest_ids))


@dataclass(frozen=True)
class DriveReadbackCapture:
    before_metadata: Mapping[str, Any]
    downloaded_bytes: bytes
    after_metadata: Mapping[str, Any]
    observed_at: datetime
    before_revision_id: str | None = None
    after_revision_id: str | None = None


class GoogleDriveReadbackStore:
    """One-shot wrapper around an injected Drive v3 transport.

    This object does not retry uploads or downloads.  A timeout is returned to
    the caller as an uncertain operation and must be reconciled by reading the
    original file identity; it must never trigger a blind second create.
    """

    def __init__(self, transport: DriveV3Transport, *, clock=lambda: datetime.now(timezone.utc)):
        self._transport = transport
        self._clock = clock

    def capture(self, file_id: str) -> DriveReadbackCapture:
        before = self._transport.get_file_metadata(file_id)
        before_revisions = self._transport.list_revisions(file_id)
        before_revision_id = _current_revision_id(before_revisions)
        body = self._transport.download_media(file_id)
        after = self._transport.get_file_metadata(file_id)
        after_revisions = self._transport.list_revisions(file_id)
        after_revision_id = _current_revision_id(after_revisions)
        return DriveReadbackCapture(
            before_metadata=before,
            downloaded_bytes=body,
            after_metadata=after,
            observed_at=self._clock(),
            before_revision_id=before_revision_id,
            after_revision_id=after_revision_id,
        )

    def verify(self, file_id: str, expected: DriveFileExpectation) -> VerifiedDriveReceipt:
        capture = self.capture(file_id)
        return verify_google_drive_readback(
            capture.before_metadata,
            capture.downloaded_bytes,
            capture.after_metadata,
            expected=expected,
            observed_at=capture.observed_at,
            before_revision_id=capture.before_revision_id,
            after_revision_id=capture.after_revision_id,
            before_revision_source="drive.revisions.list.currentRevisionId",
            after_revision_source="drive.revisions.list.currentRevisionId",
        )

    def create_once_and_verify(
        self, *, name: str, parent_id: str, mime_type: str, content: bytes,
        expected_readback_deadline: datetime | None = None,
        expected_created_not_after: datetime | None = None,
        expected_modified_not_after: datetime | None = None,
    ) -> VerifiedDriveReceipt:
        if not isinstance(content, bytes):
            raise DriveEvidenceError("upload content must be bytes")
        # Exactly one create attempt.  Do not catch/retry an uncertain result.
        created = self._transport.create_file(
            name=name, parent_id=parent_id, mime_type=mime_type, content=content
        )
        file_id = created.get("id")
        if not isinstance(file_id, str) or not file_id:
            raise DriveEvidenceError("Drive create response omitted file ID")
        expectation = DriveFileExpectation(
            file_id=file_id,
            name=name,
            parent_id=parent_id,
            mime_type=mime_type,
            sha256=sha256_bytes(content),
            size_bytes=len(content),
        expected_version=(
            str(created["version"]) if created.get("version") is not None
            else (str(created["headRevisionId"]) if created.get("headRevisionId") is not None else None)
        ),
            created_not_after=expected_created_not_after,
            modified_not_after=expected_modified_not_after,
            readback_not_after=expected_readback_deadline,
        )
        return self.verify(file_id, expectation)
