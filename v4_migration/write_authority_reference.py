"""Inactive request contract for future preselection write authorization.

Values supplied through argv or the environment are declarations only. This
module deliberately has no provider registration, file loader, dynamic import,
or positive resolution path until an owner-designated trust source and
cross-process verification contract exist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import os
from pathlib import Path
import re
from typing import Mapping, NoReturn, Sequence


AUTHORITY_REFERENCE_ENV = "V4_WRITE_AUTHORIZATION_REF"
AUTHORITY_PROVIDER_STATE = "WAITING_FOR_OWNER_DESIGNATED_TRUST_SOURCE"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_POOL_ID = re.compile(r"[A-Za-z0-9_-]+\Z")


class WriteOperation(str, Enum):
    MATERIALIZE = "MATERIALIZE"
    RECOVER_EXPECTED_MISSING = "RECOVER_EXPECTED_MISSING"
    ROLLBACK_RECOVERY = "ROLLBACK_RECOVERY"


class DeclarationSource(str, Enum):
    ARGV = "argv"
    ENV = "env"


class WriteAuthorityResolutionError(RuntimeError):
    """A write-authority declaration cannot be verified in this release."""

    def __init__(self, reason_code: str, message: str, *, source: str | None = None):
        super().__init__(message)
        self.reason_code = reason_code
        self.source = source


def _exact_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise ValueError(f"invalid exact {label}")
    return value


def _exact_date(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"\d{8}", value) is None:
        raise ValueError(f"invalid exact {label}")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"invalid exact {label}") from error
    return value


def _exact_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"invalid {label} SHA-256")
    return value


@dataclass(frozen=True)
class DispatchCorrelation:
    """Correlation claims to verify against the real dispatch and child state."""

    dispatch_run_id: str
    workload_id: str
    slot_id: str
    business_date: str
    target_date: str
    parent_identity: str
    child_identity: str

    def __post_init__(self) -> None:
        for field_name in (
            "dispatch_run_id",
            "workload_id",
            "slot_id",
            "parent_identity",
            "child_identity",
        ):
            _exact_text(getattr(self, field_name), field_name)
        _exact_date(self.business_date, "business date")
        _exact_date(self.target_date, "target date")


@dataclass(frozen=True)
class ExactWriteScope:
    """Caller-requested scope; these fields are claims until independently verified."""

    operation: WriteOperation
    trade_date: str
    pool_ids: tuple[str, ...]
    canonical_data_root: Path
    active_release_id: str
    active_release_manifest_sha256: str
    expected_gate_revision: int
    dispatch_correlation: DispatchCorrelation | None = None
    recovery_preimage_sha256: str | None = None
    recovery_replacement_sha256: str | None = None
    rollback_current_sha256: str | None = None
    rollback_recovery_record_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation, WriteOperation):
            raise ValueError("invalid write operation")
        trade_date = _exact_date(self.trade_date, "trade date")
        if (
            not isinstance(self.pool_ids, tuple)
            or not self.pool_ids
            or any(not isinstance(pool_id, str) or _POOL_ID.fullmatch(pool_id) is None for pool_id in self.pool_ids)
            or self.pool_ids != tuple(sorted(set(self.pool_ids)))
        ):
            raise ValueError("pool ids must be a nonempty, sorted exact set")
        if not isinstance(self.canonical_data_root, Path) or not self.canonical_data_root.is_absolute():
            raise ValueError("data root must be an absolute canonical Path")
        if (
            os.path.normpath(str(self.canonical_data_root)) != str(self.canonical_data_root)
            or self.canonical_data_root.resolve(strict=False) != self.canonical_data_root
        ):
            raise ValueError("data root must be canonical")
        _exact_text(self.active_release_id, "active release id")
        _exact_sha256(self.active_release_manifest_sha256, "active release manifest")
        if (
            not isinstance(self.expected_gate_revision, int)
            or isinstance(self.expected_gate_revision, bool)
            or self.expected_gate_revision < 0
        ):
            raise ValueError("expected gate revision must be a nonnegative integer")
        if self.dispatch_correlation is not None:
            if not isinstance(self.dispatch_correlation, DispatchCorrelation):
                raise ValueError("invalid dispatch correlation")
            if self.dispatch_correlation.target_date != trade_date:
                raise ValueError("dispatch target date does not match trade date")

        recovery_fields = (
            self.recovery_preimage_sha256,
            self.recovery_replacement_sha256,
            self.rollback_current_sha256,
            self.rollback_recovery_record_id,
        )
        if self.operation is WriteOperation.MATERIALIZE:
            if any(value is not None for value in recovery_fields):
                raise ValueError("materialize scope cannot contain recovery fields")
        elif self.operation is WriteOperation.RECOVER_EXPECTED_MISSING:
            if self.recovery_preimage_sha256 is None or self.recovery_replacement_sha256 is None:
                raise ValueError("recovery scope requires exact preimage and replacement SHAs")
            _exact_sha256(self.recovery_preimage_sha256, "recovery preimage")
            _exact_sha256(self.recovery_replacement_sha256, "recovery replacement")
            if any(value is not None for value in (self.rollback_current_sha256, self.rollback_recovery_record_id)):
                raise ValueError("recovery scope cannot contain rollback fields")
        elif self.operation is WriteOperation.ROLLBACK_RECOVERY:
            if self.rollback_current_sha256 is None or self.rollback_recovery_record_id is None:
                raise ValueError("rollback scope requires current SHA and recovery-record identity")
            _exact_sha256(self.rollback_current_sha256, "rollback current artifact")
            _exact_text(self.rollback_recovery_record_id, "rollback recovery-record identity")
            if any(value is not None for value in (self.recovery_preimage_sha256, self.recovery_replacement_sha256)):
                raise ValueError("rollback scope cannot contain recovery replacement fields")


@dataclass(frozen=True)
class UntrustedAuthorizationReference:
    """Opaque caller declaration, never a permit or proof of approval."""

    value: str = field(repr=False)
    source: DeclarationSource


@dataclass(frozen=True)
class WriteAuthorityRequest:
    """Future resolver request shape; constructing it grants no authority."""

    reference: UntrustedAuthorizationReference
    scope: ExactWriteScope


def resolve_write_authority_reference(
    request: WriteAuthorityRequest,
) -> NoReturn:
    """Fail closed until the owner supplies an independently trusted provider."""

    if not isinstance(request, WriteAuthorityRequest):
        raise WriteAuthorityResolutionError(
            "INVALID_AUTHORITY_REQUEST",
            "write authority request must use the typed request contract",
        )
    raise WriteAuthorityResolutionError(
        "AUTHORITY_PROVIDER_UNAVAILABLE",
        "no owner-designated write authorization provider is configured",
        source=request.reference.source.value,
    )


def reject_cli_authority_declaration(
    cli_reference: str | Sequence[str] | None,
    *,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Reject explicit argv/env declarations before a CLI reaches any writer."""

    environment = os.environ if environ is None else environ
    env_present = AUTHORITY_REFERENCE_ENV in environment
    cli_present = cli_reference is not None
    if isinstance(cli_reference, str):
        cli_values = (cli_reference,)
    elif cli_reference is None:
        cli_values = ()
    else:
        cli_values = tuple(cli_reference)
    if not cli_present and not env_present:
        return
    if len(cli_values) > 1 or (cli_present and env_present):
        raise WriteAuthorityResolutionError(
            "CONFLICTING_AUTHORITY_REFERENCE_DECLARATIONS",
            "multiple write authorization reference declarations conflict",
            source="argv+env" if env_present else "argv",
        )

    source = DeclarationSource.ARGV if cli_present else DeclarationSource.ENV
    value = cli_values[0] if cli_present else environment[AUTHORITY_REFERENCE_ENV]
    if not isinstance(value, str) or not value.strip():
        raise WriteAuthorityResolutionError(
            "EMPTY_AUTHORITY_REFERENCE_DECLARATION",
            "write authorization reference declaration is empty",
            source=source.value,
        )
    declaration = UntrustedAuthorizationReference(value=value, source=source)
    raise WriteAuthorityResolutionError(
        "AUTHORITY_PROVIDER_UNAVAILABLE",
        "declared write authorization reference is untrusted and no provider is configured",
        source=declaration.source.value,
    )
