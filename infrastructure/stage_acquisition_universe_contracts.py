"""Contracts for the strict physical A-share stage-input snapshot.

The presentation projection in :mod:`domains.preselection` is deliberately
allowed to describe missing lanes.  Stage acquisition has a narrower
authority boundary: it reads the six graph-defined A pool lanes from the
native pool store, verifies each available artifact trio, and builds a
deterministic union from the verified non-empty contributors.  Missing,
partial, and rejected lanes remain explicit provenance diagnostics.  This
module keeps that authority and the pure aggregation rules in one place so
callers cannot accidentally turn a display mapping into a physical-input
receipt.
"""
from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Iterator, Mapping

from infrastructure.data_store import _canonical_bytes, _date
from stage_center.input_contracts import (
    KNOWN_A_STAGE_POOL_IDS,
    REQUIRED_A_STAGE_POOL_IDS,
    a_pool_contract,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_A_CODE = re.compile(r"^A\.\d{6}$")
_MARKET_ALIASES = frozenset({"A", "A_SHARE", "ASHARE", "A股"})
_POLICY_NOTE_EXACT = frozenset(
    {
        "RESEARCH_ONLY_NO_BUY_GATE",
        "RESEARCH_ONLY",
        "OBSERVATION_ONLY",
        "RANK_FOR_REVIEW_ONLY_NOT_BUY_PRIORITY",
    }
)
_POOL_DIAGNOSTIC_STATUSES = frozenset(
    {
        "CANNOT_CONFIRM",
        "MISSING",
        "VALID_EMPTY",
        "FAILED",
        "SOURCE_MISSING",
        "NOT_MATERIALIZED",
        "UNAVAILABLE",
    }
)
_FORBIDDEN_OUTCOME_FIELDS = frozenset(
    {
        "future_return",
        "label_return",
        "post_event_score",
        "future_ret",
        "fwd_return",
        "forward_return",
    }
)
STRICT_POOL_SNAPSHOT_AUTHORITY = "STRICT_PHYSICAL_POOL_SNAPSHOT"


class StageAcquisitionContractError(ValueError):
    """A physical stage-input pool or aggregate cannot be confirmed."""


def _append_diagnostic(
    diagnostics: dict[str, list[str]], pool_id: str, reason: str
) -> None:
    """Add one deterministic pool-scoped diagnostic without changing order."""

    text = str(reason or "").strip()
    if text and text not in diagnostics.setdefault(pool_id, []):
        diagnostics[pool_id].append(text)


def _freeze(value: Any) -> Any:
    """Recursively freeze JSON-shaped data held by a snapshot."""

    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    """Return a mutable JSON-shaped copy for compatibility mappings."""

    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return deepcopy(value)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _semantic_sha(value: Any) -> str:
    return _sha256_bytes(_canonical_bytes(_thaw(value)))


def _canonical_code(row: Mapping[str, Any], pool_id: str, index: int) -> str:
    from infrastructure._stage_acquisition_universe_contracts_parts.primitives import __canonical_code_body as _v4_impl
    return _v4_impl(globals(), row, pool_id, index)


def _parse_date_field(key: str, value: Any, trade_date: str, location: str) -> None:
    """Reject malformed or post-trade-date signal/target metadata."""
    from infrastructure._stage_acquisition_universe_contracts_parts.primitives import __parse_date_field_body as _v4_impl
    return _v4_impl(globals(), key, value, trade_date, location)


def _walk_source_dates(value: Any, trade_date: str, location: str = "pool") -> None:
    from infrastructure._stage_acquisition_universe_contracts_parts.rows_metadata import __walk_source_dates_body as _v4_impl
    return _v4_impl(globals(), value, trade_date, location)


def _walk_forbidden_outcomes(value: Any, location: str = "pool") -> None:
    from infrastructure._stage_acquisition_universe_contracts_parts.primitives import __walk_forbidden_outcomes_body as _v4_impl
    return _v4_impl(globals(), value, location)


def validate_stage_row(
    row: Mapping[str, Any], pool_id: str, trade_date: str, index: int
) -> dict[str, Any]:
    """Validate and canonicalize one row shared by projection and strict reads."""
    from infrastructure._stage_acquisition_universe_contracts_parts.rows_metadata import _validate_stage_row_body as _v4_impl
    return _v4_impl(globals(), row, pool_id, trade_date, index)


def validate_pool_source_metadata(
    payload: Mapping[str, Any], trade_date: str, pool_id: str
) -> tuple[dict[str, Any], tuple[str, ...], tuple[str, ...]]:
    """Validate the common physical-pool identity, dates, flags, and reasons."""
    from infrastructure._stage_acquisition_universe_contracts_parts.rows_metadata import _validate_pool_source_metadata_body as _v4_impl
    return _v4_impl(globals(), payload, trade_date, pool_id)


def validate_pool_rows(
    payload: Mapping[str, Any],
    pool_id: str,
    trade_date: str,
    *,
    allow_empty: bool = False,
) -> list[dict[str, Any]]:
    """Validate all rows, including exact pool ownership and PIT/leakage fields."""
    from infrastructure._stage_acquisition_universe_contracts_parts.rows_metadata import _validate_pool_rows_body as _v4_impl
    return _v4_impl(globals(), payload, pool_id, trade_date, allow_empty=allow_empty)


def is_non_blocking_policy_note(reason: str) -> bool:
    """Return whether a cannot-confirm token is explanatory policy metadata."""

    token = str(reason or "").strip().upper()
    return token in _POLICY_NOTE_EXACT or token.startswith("RESEARCH_ONLY_")


def split_cannot_confirm(reasons: Iterable[Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split source reasons into ``(blocking, policy_notes)`` in source order."""
    from infrastructure._stage_acquisition_universe_contracts_parts.primitives import _split_cannot_confirm_body as _v4_impl
    return _v4_impl(globals(), reasons)


@dataclass(frozen=True, slots=True)
class VerifiedPoolSnapshot:
    """One exact physical pool artifact and its verified evidence trio."""

    pool_id: str
    trade_date: str
    artifact: Mapping[str, Any]
    manifest: Mapping[str, Any]
    receipt: Mapping[str, Any]
    artifact_relative_path: str
    manifest_relative_path: str
    receipt_relative_path: str
    artifact_raw_sha256: str
    manifest_raw_sha256: str
    receipt_raw_sha256: str
    pool_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact", _freeze(deepcopy(dict(self.artifact))))
        object.__setattr__(self, "manifest", _freeze(deepcopy(dict(self.manifest))))
        object.__setattr__(self, "receipt", _freeze(deepcopy(dict(self.receipt))))

    @property
    def payload(self) -> Mapping[str, Any]:
        """Alias retained for callers that call the artifact a payload."""

        return self.artifact

    @property
    def artifact_sha256(self) -> str:
        """The legacy semantic artifact SHA (equal to raw SHA for canonical JSON)."""

        return self.pool_sha256

    @property
    def raw_sha256(self) -> str:
        """Short alias for the canonical artifact's physical SHA."""

        return self.artifact_raw_sha256

    @property
    def artifact_path(self) -> str:
        return self.artifact_relative_path

    @property
    def receipt_path(self) -> str:
        return self.receipt_relative_path

    @property
    def manifest_path(self) -> str:
        return self.manifest_relative_path


@dataclass(frozen=True, slots=True)
class StrictAPreselectionSnapshot(Mapping[str, Any]):
    """Frozen, deterministic union of the six exact-date A pool snapshots.

    The Mapping implementation is intentional: existing display/read APIs can
    continue indexing ``a_all_pool_rows`` while the materializer can require
    the concrete snapshot type and its physical evidence fields.
    """

    trade_date: str
    pools: tuple[VerifiedPoolSnapshot, ...]
    codes: tuple[str, ...]
    code_sources: Mapping[str, tuple[str, ...]]
    a_all_pool_rows: tuple[Mapping[str, Any], ...]
    blocking_reasons: tuple[str, ...] = ()
    policy_notes: tuple[str, ...] = ()
    stage_selection_eligible: bool = True
    status: str = "READY"
    # Diagnostics are deliberately separate from ``blocking_reasons``.  A
    # missing or partial lane is visible and traceable, while a non-empty
    # verified A aggregate can still be consumed by stage selection.
    pool_diagnostics: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    # ``pools`` preserves the physically read snapshot even when its rows do
    # not pass contribution validation.  Keep the count that actually entered
    # the aggregate separate from the raw artifact row count so rejected
    # source rows cannot masquerade as stage-authoritative rows at publish.
    pool_contribution_counts: Mapping[str, int] = field(default_factory=dict)
    diagnostic_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "pools", tuple(self.pools))
        object.__setattr__(self, "codes", tuple(self.codes))
        object.__setattr__(
            self,
            "code_sources",
            MappingProxyType(
                {
                    str(code): tuple(str(pool_id) for pool_id in pool_ids)
                    for code, pool_ids in self.code_sources.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "a_all_pool_rows",
            tuple(_freeze(deepcopy(dict(row))) for row in self.a_all_pool_rows),
        )
        object.__setattr__(self, "blocking_reasons", tuple(self.blocking_reasons))
        object.__setattr__(self, "policy_notes", tuple(self.policy_notes))
        diagnostics: dict[str, tuple[str, ...]] = {}
        for pool_id, reasons in self.pool_diagnostics.items():
            diagnostics[str(pool_id)] = tuple(
                str(reason) for reason in reasons if str(reason).strip()
            )
        object.__setattr__(self, "pool_diagnostics", MappingProxyType(diagnostics))
        contribution_counts: dict[str, int] = {}
        for pool_id, count in self.pool_contribution_counts.items():
            if pool_id not in KNOWN_A_STAGE_POOL_IDS:
                raise StageAcquisitionContractError(
                    f"unknown A pool contribution count: {pool_id}"
                )
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise StageAcquisitionContractError(
                    f"invalid A pool contribution count: {pool_id}"
                )
            contribution_counts[str(pool_id)] = count
        object.__setattr__(
            self,
            "pool_contribution_counts",
            MappingProxyType(contribution_counts),
        )
        object.__setattr__(
            self,
            "diagnostic_reasons",
            tuple(str(reason) for reason in self.diagnostic_reasons if str(reason).strip()),
        )

    @property
    def pool_ids(self) -> tuple[str, ...]:
        return tuple(pool.pool_id for pool in self.pools)

    @property
    def known_pool_ids(self) -> tuple[str, ...]:
        return tuple(KNOWN_A_STAGE_POOL_IDS)

    @property
    def row_count(self) -> int:
        return len(self.codes)

    @property
    def ready(self) -> bool:
        return (
            self.status == "READY"
            and not self.blocking_reasons
            and self.stage_selection_eligible
        )

    def as_projection(self) -> dict[str, Any]:
        """Expose the historical projection shape without losing source data."""
        from infrastructure._stage_acquisition_universe_contracts_parts.frozen_types import _StrictAPreselectionSnapshot_as_projection_body as _v4_impl
        return _v4_impl(globals(), self)

    def __getitem__(self, key: str) -> Any:
        return self.as_projection()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.as_projection())

    def __len__(self) -> int:
        return len(self.as_projection())


def _snapshot_from_store_result(
    result: Mapping[str, Any], trade_date: str, pool_id: str
) -> VerifiedPoolSnapshot:
    from infrastructure._stage_acquisition_universe_contracts_parts.snapshot_verification import __snapshot_from_store_result_body as _v4_impl
    return _v4_impl(globals(), result, trade_date, pool_id)


def validate_verified_pool_snapshot(
    snapshot: VerifiedPoolSnapshot,
    trade_date: str,
    pool_id: str,
    *,
    allow_diagnostics: bool = False,
) -> tuple[list[dict[str, Any]], tuple[str, ...], tuple[str, ...]]:
    """Validate one verified snapshot and return rows plus reason classes."""
    from infrastructure._stage_acquisition_universe_contracts_parts.snapshot_verification import _validate_verified_pool_snapshot_body as _v4_impl
    return _v4_impl(globals(), snapshot, trade_date, pool_id, allow_diagnostics=allow_diagnostics)


def aggregate_verified_pool_snapshots(
    snapshots: Iterable[VerifiedPoolSnapshot],
    trade_date: str,
    *,
    pool_diagnostics: Mapping[str, Iterable[str]] | None = None,
) -> StrictAPreselectionSnapshot:
    """Aggregate the known A lanes, accepting any verified non-empty subset.

    Every known lane still has a fixed provenance slot.  Missing, empty, or
    rejected lanes are recorded under their pool ID; they are not allowed to
    erase rows contributed by another valid lane.  The aggregate only becomes
    blocked when no valid A rows remain.
    """
    from infrastructure._stage_acquisition_universe_contracts_parts.snapshot_aggregation import _aggregate_verified_pool_snapshots_body as _v4_impl
    return _v4_impl(globals(), snapshots, trade_date, pool_diagnostics=pool_diagnostics)


def validate_strict_stage_acquisition_artifact(
    payload: Mapping[str, Any],
) -> str:
    """Validate the immutable artifact's strict physical-pool authority.

    This is intentionally independent of the store implementation so the
    publication boundary can remain a small call into one pure contract.  A
    mapping/display artifact may still be built for diagnostics, but it cannot
    satisfy this validator and therefore cannot create or advance ``current``.
    """
    from infrastructure._stage_acquisition_universe_contracts_parts.strict_artifact import _validate_strict_stage_acquisition_artifact_body as _v4_impl
    return _v4_impl(globals(), payload)


def _snapshot_pool_provenance(
    snapshot: StrictAPreselectionSnapshot,
) -> list[dict[str, Any]]:
    """Derive the exact stage provenance representation from one snapshot."""
    from infrastructure._stage_acquisition_universe_contracts_parts.snapshot_provenance import __snapshot_pool_provenance_body as _v4_impl
    return _v4_impl(globals(), snapshot)


def snapshot_pool_provenance(
    snapshot: StrictAPreselectionSnapshot,
) -> list[dict[str, Any]]:
    """Public alias for the immutable six-lane provenance projection."""

    return _snapshot_pool_provenance(snapshot)


def _snapshot_projection_sha256(snapshot: StrictAPreselectionSnapshot) -> str:
    projection = snapshot.as_projection()
    return _semantic_sha(
        {key: value for key, value in projection.items() if key != "strict_snapshot"}
    )


def validate_artifact_against_snapshot(
    artifact: Mapping[str, Any], snapshot: StrictAPreselectionSnapshot
) -> None:
    """Require every strict artifact binding to match a fresh physical read."""
    from infrastructure._stage_acquisition_universe_contracts_parts.snapshot_provenance import _validate_artifact_against_snapshot_body as _v4_impl
    return _v4_impl(globals(), artifact, snapshot)


def read_strict_a_preselection_snapshot(
    store: Any,
    trade_date: str,
    _limit: int | None = None,
    *,
    lock_lease: object | None = None,
) -> StrictAPreselectionSnapshot:
    """Read the known physical pool trios once and return one frozen snapshot.

    A lane read failure is scoped to that lane.  The aggregate remains
    eligible when another verified lane contributes rows; no source is
    replaced with ``latest`` or a display projection.
    """
    from infrastructure._stage_acquisition_universe_contracts_parts.snapshot_publication import _read_strict_a_preselection_snapshot_body as _v4_impl
    return _v4_impl(globals(), store, trade_date, _limit, lock_lease)


def build_strict_stage_acquisition_universe(
    snapshot: StrictAPreselectionSnapshot,
) -> dict[str, Any]:
    """Build the stage artifact from the frozen physical snapshot."""
    from infrastructure._stage_acquisition_universe_contracts_parts.snapshot_publication import _build_strict_stage_acquisition_universe_body as _v4_impl
    return _v4_impl(globals(), snapshot)


__all__ = [
    "STRICT_POOL_SNAPSHOT_AUTHORITY",
    "StageAcquisitionContractError",
    "StrictAPreselectionSnapshot",
    "VerifiedPoolSnapshot",
    "aggregate_verified_pool_snapshots",
    "build_strict_stage_acquisition_universe",
    "is_non_blocking_policy_note",
    "read_strict_a_preselection_snapshot",
    "snapshot_pool_provenance",
    "split_cannot_confirm",
    "validate_artifact_against_snapshot",
    "validate_pool_rows",
    "validate_pool_source_metadata",
    "validate_stage_row",
    "validate_strict_stage_acquisition_artifact",
    "validate_verified_pool_snapshot",
]
