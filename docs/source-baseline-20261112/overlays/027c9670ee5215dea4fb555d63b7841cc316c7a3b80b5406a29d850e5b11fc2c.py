"""Contracts for the strict physical A-share stage-input snapshot.

The presentation projection in :mod:`domains.preselection` is deliberately
allowed to describe missing lanes.  Stage acquisition has a narrower
authority boundary: it reads the six graph-defined A pools from the native
pool store, verifies the bytes and their artifact trio, and only then builds a
deterministic union.  This module keeps that authority and the pure
aggregation rules in one place so callers cannot accidentally turn a display
mapping into a physical-input receipt.
"""
from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Iterator, Mapping

from infrastructure.data_store import _canonical_bytes, _date
from stage_center.input_contracts import (
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
    value = row.get("symbol")
    if value in (None, ""):
        value = row.get("normalized_code")
    if value in (None, ""):
        value = row.get("code")
    if value in (None, ""):
        value = row.get("stock_code")
    if value in (None, ""):
        value = row.get("ts_code")
    text = str(value or "").strip().upper()
    if text.endswith((".SH", ".SZ", ".BJ")):
        text = text[:-3]
    if re.fullmatch(r"\d{6}", text):
        text = f"A.{text}"
    if not _A_CODE.fullmatch(text):
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} row {index} has invalid code"
        )
    market = str(row.get("market") or "").strip().upper()
    if market and market not in _MARKET_ALIASES:
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} row {index} is not market A"
        )
    return text


def _parse_date_field(key: str, value: Any, trade_date: str, location: str) -> None:
    """Reject malformed or post-trade-date signal/target metadata."""

    if value in (None, ""):
        return
    text = str(value).strip()
    try:
        parsed = _date(text)
    except ValueError as error:
        raise StageAcquisitionContractError(
            f"{location} {key} is not an exact date"
        ) from error
    if parsed > trade_date:
        raise StageAcquisitionContractError(
            f"{location} {key} is a future date"
        )


def _walk_source_dates(value: Any, trade_date: str, location: str = "pool") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            folded = str(key).casefold()
            # These are the date-bearing fields that can turn a post-event or
            # future target into a stage-input row.  Other evidence timestamps
            # are intentionally left as descriptive metadata.
            if (
                folded in {"signal_date", "target_date", "future_signal_date", "future_target_date"}
                or "signal_date" in folded
                or "target_date" in folded
            ):
                _parse_date_field(str(key), nested, trade_date, location)
            _walk_source_dates(nested, trade_date, f"{location}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _walk_source_dates(nested, trade_date, f"{location}[{index}]")
    elif isinstance(value, tuple):
        for index, nested in enumerate(value):
            _walk_source_dates(nested, trade_date, f"{location}[{index}]")


def _walk_forbidden_outcomes(value: Any, location: str = "pool") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            folded = str(key).casefold()
            if (
                folded in _FORBIDDEN_OUTCOME_FIELDS
                or any(token in folded for token in ("future_", "label_", "post_event_"))
            ):
                raise StageAcquisitionContractError(
                    f"{location}.{key} is a forbidden future outcome field"
                )
            _walk_forbidden_outcomes(nested, f"{location}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _walk_forbidden_outcomes(nested, f"{location}[{index}]")


def validate_stage_row(
    row: Mapping[str, Any], pool_id: str, trade_date: str, index: int
) -> dict[str, Any]:
    """Validate and canonicalize one row shared by projection and strict reads."""

    if not isinstance(row, Mapping):
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} row {index} is invalid"
        )
    if "pool_id" not in row or str(row.get("pool_id") or "") != pool_id:
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} row {index} pool identity is not bound"
        )
    _walk_forbidden_outcomes(row, f"pool[{pool_id}].row[{index}]")
    _walk_source_dates(row, trade_date, f"pool[{pool_id}].row[{index}]")
    if "stage_selection_eligible" in row and row.get("stage_selection_eligible") is not True:
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} row {index} cannot be confirmed: "
            "stage_selection_eligible is not true"
        )
    code = _canonical_code(row, pool_id, index)
    normalized = dict(row)
    normalized["symbol"] = code
    normalized["market"] = "A"
    normalized["pool_id"] = pool_id
    return normalized


def validate_pool_source_metadata(
    payload: Mapping[str, Any], trade_date: str, pool_id: str
) -> tuple[dict[str, Any], tuple[str, ...], tuple[str, ...]]:
    """Validate the common physical-pool identity, dates, flags, and reasons."""

    if not isinstance(payload, Mapping):
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} artifact is not an object"
        )
    if str(payload.get("pool_id") or "") != pool_id:
        raise StageAcquisitionContractError(f"required A pool {pool_id} identity mismatch")
    if str(payload.get("trade_date") or "") != trade_date:
        raise StageAcquisitionContractError(f"required A pool {pool_id} date mismatch")
    if str(payload.get("market") or "").strip().upper() != "A":
        raise StageAcquisitionContractError(f"required A pool {pool_id} market mismatch")
    expected_status, expected_producer, expected_role = a_pool_contract(pool_id)
    if payload.get("status") != expected_status:
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} status is not confirmed"
        )
    if payload.get("producer_id") != expected_producer:
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} producer identity mismatch"
        )
    if payload.get("source_role") != expected_role:
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} source role mismatch"
        )
    source_path = str(payload.get("source_path") or "").strip()
    source_sha = str(payload.get("source_sha256") or "").lower()
    if not source_path or _SHA256.fullmatch(source_sha) is None:
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} artifact identity is incomplete"
        )
    if "target_date" in payload and str(payload.get("target_date") or "") != trade_date:
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} target_date mismatch"
        )
    _walk_forbidden_outcomes(payload, f"pool[{pool_id}]")
    _walk_source_dates(payload, trade_date, f"pool[{pool_id}]")
    for field in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if payload.get(field) is not False:
            raise StageAcquisitionContractError(
                f"required A pool {pool_id} safety boundary mismatch"
            )
    eligibility = payload.get("stage_selection_eligible")
    if "stage_selection_eligible" in payload and eligibility is not True:
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} cannot be confirmed: "
            "stage_selection_eligible is not true"
        )
    reasons = payload.get("cannot_confirm")
    if not isinstance(reasons, list) or any(not isinstance(item, str) for item in reasons):
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} cannot_confirm is invalid"
        )
    blocking, notes = split_cannot_confirm(reasons)
    return dict(payload), blocking, notes


def validate_pool_rows(
    payload: Mapping[str, Any], pool_id: str, trade_date: str
) -> list[dict[str, Any]]:
    """Validate all rows, including exact pool ownership and PIT/leakage fields."""

    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise StageAcquisitionContractError(f"required A pool {pool_id} has no rows")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_row in enumerate(rows):
        row = validate_stage_row(raw_row, pool_id, trade_date, index)
        code = row["symbol"]
        if code in seen:
            raise StageAcquisitionContractError(
                f"required A pool {pool_id} contains duplicate code {code}"
            )
        seen.add(code)
        normalized.append(row)
    return normalized


def is_non_blocking_policy_note(reason: str) -> bool:
    """Return whether a cannot-confirm token is explanatory policy metadata."""

    token = str(reason or "").strip().upper()
    return token in _POLICY_NOTE_EXACT or token.startswith("RESEARCH_ONLY_")


def split_cannot_confirm(reasons: Iterable[Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split source reasons into ``(blocking, policy_notes)`` in source order."""

    blocking: list[str] = []
    notes: list[str] = []
    for raw in reasons:
        reason = str(raw or "").strip()
        if not reason:
            continue
        target = notes if is_non_blocking_policy_note(reason) else blocking
        if reason not in target:
            target.append(reason)
    return tuple(blocking), tuple(notes)


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

    @property
    def pool_ids(self) -> tuple[str, ...]:
        return tuple(pool.pool_id for pool in self.pools)

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

        pools = [_thaw(pool.artifact) for pool in self.pools]
        rows = [_thaw(row) for row in self.a_all_pool_rows]
        return {
            "ok": self.ready,
            "trade_date": self.trade_date,
            "data_status": "READY_WITH_ROWS" if self.ready else "CANNOT_CONFIRM",
            "status": "READY_WITH_ROWS" if self.ready else "CANNOT_CONFIRM",
            "codes": list(self.codes),
            "row_count": len(self.codes),
            "pools": pools,
            "a_all_pool_rows": rows,
            "a_all_pool_row_count": len(rows),
            "code_sources": {
                code: list(pool_ids) for code, pool_ids in self.code_sources.items()
            },
            "cannot_confirm": list(self.blocking_reasons),
            "blocking_reasons": list(self.blocking_reasons),
            "policy_notes": list(self.policy_notes),
            "stage_selection_eligible": self.stage_selection_eligible,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "strict_snapshot": True,
        }

    def __getitem__(self, key: str) -> Any:
        return self.as_projection()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.as_projection())

    def __len__(self) -> int:
        return len(self.as_projection())


def _snapshot_from_store_result(
    result: Mapping[str, Any], trade_date: str, pool_id: str
) -> VerifiedPoolSnapshot:
    artifact = result.get("artifact", result.get("payload"))
    manifest = result.get("manifest")
    receipt = result.get("receipt")
    if not all(isinstance(item, Mapping) for item in (artifact, manifest, receipt)):
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} physical snapshot is incomplete"
        )
    fields = {
        "artifact_relative_path": result.get("artifact_relative_path", result.get("artifact_relative")),
        "manifest_relative_path": result.get("manifest_relative_path", result.get("manifest_relative")),
        "receipt_relative_path": result.get("receipt_relative_path", result.get("receipt_relative")),
        "artifact_raw_sha256": result.get("artifact_raw_sha256"),
        "manifest_raw_sha256": result.get("manifest_raw_sha256"),
        "receipt_raw_sha256": result.get("receipt_raw_sha256"),
        "pool_sha256": result.get("pool_sha256", result.get("semantic_sha256")),
    }
    if any(not isinstance(value, str) or not value for value in fields.values()):
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} physical snapshot identity is incomplete"
        )
    for name in (
        "artifact_raw_sha256",
        "manifest_raw_sha256",
        "receipt_raw_sha256",
        "pool_sha256",
    ):
        if _SHA256.fullmatch(fields[name]) is None:
            raise StageAcquisitionContractError(
                f"required A pool {pool_id} {name} is invalid"
            )
    expected_artifact = f"preselection_pools/{trade_date}/{pool_id}.json"
    expected_manifest = f"preselection_pools/{trade_date}/manifest.json"
    expected_receipt = f"preselection_pools/{trade_date}/receipts/{pool_id}.json"
    if (
        fields["artifact_relative_path"] != expected_artifact
        or fields["manifest_relative_path"] != expected_manifest
        or fields["receipt_relative_path"] != expected_receipt
    ):
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} relative path is not bound"
        )
    return VerifiedPoolSnapshot(
        pool_id=pool_id,
        trade_date=trade_date,
        artifact=artifact,
        manifest=manifest,
        receipt=receipt,
        **fields,
    )


def validate_verified_pool_snapshot(
    snapshot: VerifiedPoolSnapshot, trade_date: str, pool_id: str
) -> tuple[list[dict[str, Any]], tuple[str, ...], tuple[str, ...]]:
    """Validate one verified snapshot and return rows plus reason classes."""

    if not isinstance(snapshot, VerifiedPoolSnapshot):
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} snapshot type is invalid"
        )
    if snapshot.pool_id != pool_id or snapshot.trade_date != trade_date:
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} physical identity mismatch"
        )
    # Snapshot payloads are recursively frozen; validation works on a local
    # mutable JSON-shaped view so the existing list/object contract remains
    # exact without exposing mutability through the dataclass.
    payload = _thaw(snapshot.artifact)
    payload, blocking, notes = validate_pool_source_metadata(
        payload, trade_date, pool_id
    )
    if snapshot.pool_sha256 != _semantic_sha(payload):
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} semantic SHA mismatch"
        )
    for name in ("artifact_raw_sha256", "manifest_raw_sha256", "receipt_raw_sha256"):
        if _SHA256.fullmatch(getattr(snapshot, name)) is None:
            raise StageAcquisitionContractError(
                f"required A pool {pool_id} {name} is invalid"
            )
    expected_artifact = f"preselection_pools/{trade_date}/{pool_id}.json"
    expected_manifest = f"preselection_pools/{trade_date}/manifest.json"
    expected_receipt = f"preselection_pools/{trade_date}/receipts/{pool_id}.json"
    if (
        snapshot.artifact_relative_path != expected_artifact
        or snapshot.manifest_relative_path != expected_manifest
        or snapshot.receipt_relative_path != expected_receipt
    ):
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} relative path is not bound"
        )
    if (
        snapshot.artifact_raw_sha256 != _semantic_sha(payload)
        or snapshot.manifest_raw_sha256 != _semantic_sha(snapshot.manifest)
        or snapshot.receipt_raw_sha256 != _semantic_sha(snapshot.receipt)
    ):
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} physical SHA mismatch"
        )
    if snapshot.manifest.get(pool_id) != snapshot.pool_sha256:
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} manifest binding mismatch"
        )
    expected_receipt_payload = {
        "schema_version": "v3_5.preselection_pool_receipt.v1",
        "trade_date": trade_date,
        "pool_id": pool_id,
        "artifact_path": expected_artifact,
        "artifact_sha256": snapshot.pool_sha256,
        "source_sha256": payload.get("source_sha256"),
        "source_role": payload.get("source_role"),
    }
    for key in ("source_row_count", "source_run_id"):
        if key in payload:
            expected_receipt_payload[key] = payload[key]
    if dict(_thaw(snapshot.receipt)) != expected_receipt_payload:
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} receipt binding mismatch"
        )
    if blocking:
        raise StageAcquisitionContractError(
            f"required A pool {pool_id} cannot be confirmed: {', '.join(blocking)}"
        )
    return validate_pool_rows(payload, pool_id, trade_date), blocking, notes


def aggregate_verified_pool_snapshots(
    snapshots: Iterable[VerifiedPoolSnapshot], trade_date: str
) -> StrictAPreselectionSnapshot:
    """Aggregate exactly six verified pools in graph order."""

    try:
        date = _date(str(trade_date))
    except ValueError as error:
        raise StageAcquisitionContractError("required A pool trade date is invalid") from error
    items = tuple(snapshots)
    if len(items) != len(REQUIRED_A_STAGE_POOL_IDS):
        raise StageAcquisitionContractError(
            "required A pool set must contain exactly six physical pools"
        )
    if any(not isinstance(item, VerifiedPoolSnapshot) for item in items):
        raise StageAcquisitionContractError(
            "required A pool set contains an invalid physical snapshot"
        )
    if tuple(item.pool_id for item in items) != REQUIRED_A_STAGE_POOL_IDS:
        raise StageAcquisitionContractError(
            "required A pool set order or identity is invalid"
        )
    all_rows: list[dict[str, Any]] = []
    codes: list[str] = []
    code_sources: dict[str, list[str]] = {}
    blocking: list[str] = []
    notes: list[str] = []
    for snapshot, pool_id in zip(items, REQUIRED_A_STAGE_POOL_IDS):
        rows, pool_blocking, pool_notes = validate_verified_pool_snapshot(
            snapshot, date, pool_id
        )
        blocking.extend(
            f"{pool_id}:{reason}" for reason in pool_blocking if reason
        )
        for reason in pool_notes:
            if reason not in notes:
                notes.append(reason)
        for row in rows:
            code = row["symbol"]
            sources = code_sources.setdefault(code, [])
            if pool_id not in sources:
                sources.append(pool_id)
            if code not in codes:
                codes.append(code)
                all_rows.append(row)
    if blocking:
        raise StageAcquisitionContractError(
            "required A pool set cannot be confirmed: " + "; ".join(blocking)
        )
    return StrictAPreselectionSnapshot(
        trade_date=date,
        pools=items,
        codes=tuple(codes),
        code_sources={code: tuple(source_ids) for code, source_ids in code_sources.items()},
        a_all_pool_rows=tuple(all_rows),
        blocking_reasons=(),
        policy_notes=tuple(notes),
        stage_selection_eligible=True,
        status="READY",
    )


def validate_strict_stage_acquisition_artifact(
    payload: Mapping[str, Any],
) -> str:
    """Validate the immutable artifact's strict physical-pool authority.

    This is intentionally independent of the store implementation so the
    publication boundary can remain a small call into one pure contract.  A
    mapping/display artifact may still be built for diagnostics, but it cannot
    satisfy this validator and therefore cannot create or advance ``current``.
    """

    if not isinstance(payload, Mapping):
        raise StageAcquisitionContractError(
            "stage-acquisition artifact must be an object"
        )
    if payload.get("authority") != STRICT_POOL_SNAPSHOT_AUTHORITY:
        raise StageAcquisitionContractError(
            "stage-acquisition artifact authority must be "
            f"{STRICT_POOL_SNAPSHOT_AUTHORITY}"
        )
    trade_date = str(payload.get("trade_date") or "")
    try:
        trade_date = _date(trade_date)
    except ValueError as error:
        raise StageAcquisitionContractError(
            "stage-acquisition artifact trade date is invalid"
        ) from error

    if payload.get("status") != "READY":
        raise StageAcquisitionContractError(
            "strict stage-acquisition artifact must be READY"
        )
    if payload.get("source_projection_status") != "READY_WITH_ROWS":
        raise StageAcquisitionContractError(
            "strict stage-acquisition projection is not READY_WITH_ROWS"
        )
    if payload.get("cannot_confirm") != []:
        raise StageAcquisitionContractError(
            "strict stage-acquisition artifact cannot_confirm must be empty"
        )
    if payload.get("stage_selection_eligible") is not True:
        raise StageAcquisitionContractError(
            "strict stage-acquisition artifact stage_selection_eligible must be true"
        )
    notes = payload.get("policy_notes")
    if not isinstance(notes, list) or any(not isinstance(item, str) for item in notes):
        raise StageAcquisitionContractError(
            "strict stage-acquisition artifact policy_notes are invalid"
        )

    provenance = payload.get("source_pool_provenance")
    if not isinstance(provenance, list) or len(provenance) != len(REQUIRED_A_STAGE_POOL_IDS):
        raise StageAcquisitionContractError(
            "strict stage-acquisition source pool provenance must contain exactly six pools"
        )
    expected_paths = {
        pool_id: {
            "artifact_relative_path": f"preselection_pools/{trade_date}/{pool_id}.json",
            "manifest_relative_path": f"preselection_pools/{trade_date}/manifest.json",
            "receipt_relative_path": f"preselection_pools/{trade_date}/receipts/{pool_id}.json",
        }
        for pool_id in REQUIRED_A_STAGE_POOL_IDS
    }
    for index, (item, expected_pool_id) in enumerate(
        zip(provenance, REQUIRED_A_STAGE_POOL_IDS)
    ):
        if not isinstance(item, Mapping) or item.get("pool_id") != expected_pool_id:
            raise StageAcquisitionContractError(
                "strict stage-acquisition source pool provenance order or identity is invalid"
            )
        expected_status = a_pool_contract(expected_pool_id)[0]
        if item.get("status") != expected_status:
            raise StageAcquisitionContractError(
                f"strict stage-acquisition source pool {expected_pool_id} status is invalid"
            )
        count = item.get("row_count")
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise StageAcquisitionContractError(
                f"strict stage-acquisition source pool {expected_pool_id} row_count is invalid"
            )
        for field in (
            "pool_sha256",
            "artifact_raw_sha256",
            "manifest_raw_sha256",
            "receipt_raw_sha256",
        ):
            value = item.get(field)
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise StageAcquisitionContractError(
                    f"strict stage-acquisition source pool {expected_pool_id} {field} is invalid"
                )
        for field, expected in expected_paths[expected_pool_id].items():
            if item.get(field) != expected:
                raise StageAcquisitionContractError(
                    f"strict stage-acquisition source pool {expected_pool_id} {field} is not bound"
                )

    if payload.get("source_pool_provenance_sha256") != _semantic_sha(provenance):
        raise StageAcquisitionContractError(
            "strict stage-acquisition source pool provenance SHA mismatch"
        )

    codes = payload.get("codes")
    if not isinstance(codes, list) or not codes:
        raise StageAcquisitionContractError(
            "strict stage-acquisition codes are missing"
        )
    code_sources = payload.get("code_sources")
    if not isinstance(code_sources, Mapping) or list(code_sources) != codes:
        raise StageAcquisitionContractError(
            "strict stage-acquisition code source ordering is invalid"
        )
    pool_positions = {
        pool_id: index for index, pool_id in enumerate(REQUIRED_A_STAGE_POOL_IDS)
    }
    for code in codes:
        if not isinstance(code, str) or _A_CODE.fullmatch(code) is None:
            raise StageAcquisitionContractError(
                "strict stage-acquisition code source contains an invalid code"
            )
        sources = code_sources.get(code)
        if not isinstance(sources, list) or not sources:
            raise StageAcquisitionContractError(
                f"strict stage-acquisition code {code} has no source pool"
            )
        if any(source not in pool_positions for source in sources):
            raise StageAcquisitionContractError(
                f"strict stage-acquisition code {code} has an invalid source pool"
            )
        if len(set(sources)) != len(sources) or list(sources) != sorted(
            sources, key=pool_positions.__getitem__
        ):
            raise StageAcquisitionContractError(
                f"strict stage-acquisition code {code} source pools are not ordered"
            )
    return trade_date


def _snapshot_pool_provenance(
    snapshot: StrictAPreselectionSnapshot,
) -> list[dict[str, Any]]:
    """Derive the exact stage provenance representation from one snapshot."""

    return [
        {
            "pool_id": pool.pool_id,
            "status": str(pool.artifact.get("status") or ""),
            "row_count": len(pool.artifact.get("rows", [])),
            "pool_sha256": pool.pool_sha256,
            "artifact_raw_sha256": pool.artifact_raw_sha256,
            "manifest_raw_sha256": pool.manifest_raw_sha256,
            "receipt_raw_sha256": pool.receipt_raw_sha256,
            "artifact_relative_path": pool.artifact_relative_path,
            "manifest_relative_path": pool.manifest_relative_path,
            "receipt_relative_path": pool.receipt_relative_path,
        }
        for pool in snapshot.pools
    ]


def _snapshot_projection_sha256(snapshot: StrictAPreselectionSnapshot) -> str:
    projection = snapshot.as_projection()
    return _semantic_sha(
        {key: value for key, value in projection.items() if key != "strict_snapshot"}
    )


def validate_artifact_against_snapshot(
    artifact: Mapping[str, Any], snapshot: StrictAPreselectionSnapshot
) -> None:
    """Require every strict artifact binding to match a fresh physical read."""

    if not isinstance(snapshot, StrictAPreselectionSnapshot) or not snapshot.ready:
        raise StageAcquisitionContractError(
            "required A pool strict snapshot is not READY"
        )
    validate_strict_stage_acquisition_artifact(artifact)
    if artifact.get("trade_date") != snapshot.trade_date:
        raise StageAcquisitionContractError(
            "stage-acquisition artifact trade_date does not match physical snapshot"
        )
    expected_codes = list(snapshot.codes)
    if artifact.get("codes") != expected_codes:
        raise StageAcquisitionContractError(
            "stage-acquisition artifact codes do not match physical snapshot"
        )
    if artifact.get("row_count") != len(expected_codes):
        raise StageAcquisitionContractError(
            "stage-acquisition artifact rows do not match physical snapshot"
        )
    if artifact.get("codes_sha256") != _semantic_sha(expected_codes):
        raise StageAcquisitionContractError(
            "stage-acquisition artifact codes SHA does not match physical snapshot"
        )
    if artifact.get("source_projection_row_count") != len(expected_codes):
        raise StageAcquisitionContractError(
            "stage-acquisition artifact projection rows do not match physical snapshot"
        )
    if artifact.get("source_projection_sha256") != _snapshot_projection_sha256(snapshot):
        raise StageAcquisitionContractError(
            "stage-acquisition artifact projection SHA does not match physical snapshot"
        )
    expected_provenance = _snapshot_pool_provenance(snapshot)
    if artifact.get("source_pool_provenance") != expected_provenance:
        raise StageAcquisitionContractError(
            "stage-acquisition artifact pool provenance does not match physical snapshot"
        )
    if artifact.get("source_pool_provenance_sha256") != _semantic_sha(
        expected_provenance
    ):
        raise StageAcquisitionContractError(
            "stage-acquisition artifact provenance SHA does not match physical snapshot"
        )
    expected_sources = {
        code: list(pool_ids) for code, pool_ids in snapshot.code_sources.items()
    }
    if artifact.get("code_sources") != expected_sources:
        raise StageAcquisitionContractError(
            "stage-acquisition artifact code sources do not match physical snapshot"
        )
    if artifact.get("policy_notes") != list(snapshot.policy_notes):
        raise StageAcquisitionContractError(
            "stage-acquisition artifact policy notes do not match physical snapshot"
        )


def read_strict_a_preselection_snapshot(
    store: Any, trade_date: str, _limit: int | None = None
) -> StrictAPreselectionSnapshot:
    """Read the six physical pool trios once and return one frozen snapshot."""

    try:
        date = _date(str(trade_date))
    except ValueError as error:
        raise StageAcquisitionContractError("required A pool trade date is invalid") from error
    from infrastructure.preselection_pool_store import PreselectionPoolStore

    # ``Path`` itself has a ``root`` property (``/`` on POSIX); inspect paths
    # before looking for the NativeDataStore root attribute.
    root = Path(store) if isinstance(store, (str, Path)) else Path(getattr(store, "root", store))
    pool_store = store if isinstance(store, PreselectionPoolStore) else PreselectionPoolStore(root)
    snapshots: list[VerifiedPoolSnapshot] = []
    for pool_id in REQUIRED_A_STAGE_POOL_IDS:
        try:
            result = pool_store.read_pool_snapshot(date, pool_id)
            snapshots.append(_snapshot_from_store_result(result, date, pool_id))
        except Exception as error:
            if isinstance(error, StageAcquisitionContractError):
                raise
            raise StageAcquisitionContractError(
                f"required A pool {pool_id} cannot be confirmed: {error}"
            ) from error
    return aggregate_verified_pool_snapshots(snapshots, date)


def build_strict_stage_acquisition_universe(
    snapshot: StrictAPreselectionSnapshot,
) -> dict[str, Any]:
    """Build the stage artifact from the frozen physical snapshot."""

    if not isinstance(snapshot, StrictAPreselectionSnapshot):
        raise StageAcquisitionContractError(
            "strict stage-acquisition builder requires StrictAPreselectionSnapshot"
        )
    if not snapshot.ready:
        raise StageAcquisitionContractError(
            "strict stage-acquisition snapshot is not READY"
        )
    provenance = _snapshot_pool_provenance(snapshot)
    projection_digest = _snapshot_projection_sha256(snapshot)
    artifact = {
        "schema_version": "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V2",
        "artifact_role": "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V2",
        "artifact_version": "V2",
        "authority": STRICT_POOL_SNAPSHOT_AUTHORITY,
        "status": "READY",
        "trade_date": snapshot.trade_date,
        "codes": list(snapshot.codes),
        "row_count": len(snapshot.codes),
        "codes_sha256": _semantic_sha(list(snapshot.codes)),
        "source_projection_sha256": projection_digest,
        "source_projection_row_count": len(snapshot.codes),
        "source_projection_status": "READY_WITH_ROWS",
        "source_pool_provenance": provenance,
        "source_pool_provenance_sha256": _semantic_sha(provenance),
        "code_sources": {
            code: list(pool_ids) for code, pool_ids in snapshot.code_sources.items()
        },
        "source_merge_role": "STAGE_ACQUISITION_INPUT",
        "stage_selection_eligible": True,
        "policy_notes": list(snapshot.policy_notes),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "cannot_confirm": [],
    }
    return artifact


__all__ = [
    "STRICT_POOL_SNAPSHOT_AUTHORITY",
    "StageAcquisitionContractError",
    "StrictAPreselectionSnapshot",
    "VerifiedPoolSnapshot",
    "aggregate_verified_pool_snapshots",
    "build_strict_stage_acquisition_universe",
    "is_non_blocking_policy_note",
    "read_strict_a_preselection_snapshot",
    "split_cannot_confirm",
    "validate_artifact_against_snapshot",
    "validate_pool_rows",
    "validate_pool_source_metadata",
    "validate_stage_row",
    "validate_strict_stage_acquisition_artifact",
    "validate_verified_pool_snapshot",
]
