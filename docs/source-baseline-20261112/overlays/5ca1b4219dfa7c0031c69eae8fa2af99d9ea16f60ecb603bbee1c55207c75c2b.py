"""Strict RAW_BYTES_V1 publication for the stage-acquisition candidate chain.

The V2 store remains available through its explicitly named legacy method.  This
module owns the new immutable ``artifact -> manifest -> receipt -> commit ->
current`` chain so the store facade does not grow another copy of the protocol.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from infrastructure.interprocess_lock import owned_interprocess_lock
from infrastructure.secure_evidence_fs import (
    ReadBytesResult,
    SecureEvidenceConflict,
    SecureEvidenceRoot,
    SecureEvidenceUnavailable,
)
from infrastructure.stage_acquisition_universe_contracts import (
    StageAcquisitionContractError,
    StrictAPreselectionSnapshot,
    _is_non_contributing_source_only_lane,
    read_strict_a_preselection_snapshot,
    snapshot_pool_provenance,
    validate_artifact_against_snapshot,
)
from stage_center.input_contracts import REQUIRED_A_STAGE_POOL_IDS, a_pool_contract


STRICT_ROLE = "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V3"
STRICT_ARTIFACT_SCHEMA = "v3_5.stage_acquisition_universe.artifact.v3"
STRICT_MANIFEST_SCHEMA = "v3_5.stage_acquisition_universe.manifest.v3"
STRICT_RECEIPT_SCHEMA = "v3_5.stage_acquisition_universe.receipt.v3"
STRICT_COMMIT_SCHEMA = "v3_5.stage_acquisition_universe.commit.v2"
STRICT_CURRENT_SCHEMA = "v3_5.stage_acquisition_universe.current.v3"
STRICT_SUPERSESSION_SCHEMA = "v3_5.stage_acquisition_universe.supersession.v2"
DIGEST_MODE = "RAW_BYTES_V1"
COMMIT_STATUS = "COMMITTED"
STRICT_ARTIFACT_VERSION = "V3"
STRICT_SUCCESSOR_EVOLUTION = "EXACT_DATE_ALL_A_AGGREGATE_EXTENSION"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_RUN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")
_CODE = re.compile(r"^A\.\d{6}$")
_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
_OWNER = "V3_5_STAGE_CENTER"
_PRODUCER = "ops.materialize_stage_acquisition_universe"
_LANE = "A_SHARE_STAGE_ACQUISITION"
_MAX_BYTES = 64 * 1024 * 1024
# The pool store only exposes an append-only refresh seam for the hourly
# research recommendation lane.  Other physical lanes are immutable once a
# strict current has been published; a changed raw SHA there is a conflict.
_APPEND_ONLY_POOL_IDS = frozenset({"a_share_research_recommendation_pool"})

# A strict stage artifact is evidence input only.  Unknown extension fields are
# not allowed to smuggle an action, post-event label, or target outcome through
# the normalizer (which intentionally copies only the known V3 fields).  Keep
# the three required safety flags explicit: they are policy assertions and are
# validated as false by ``_false_flags`` below, rather than treated as action
# instructions.
_STRICT_SAFE_FLAG_KEYS = frozenset(
    {"production_allowed", "buy_gate_updated", "orders_sent"}
)
_STRICT_ACTION_KEYS = frozenset(
    {
        "buy",
        "sell",
        "order",
        "orders",
        "trade",
        "side",
        "action",
        "signal",
        "order_id",
        "order_type",
        "trade_id",
        "trade_type",
        "signal_id",
        "signal_type",
    }
)
_STRICT_OUTCOME_KEYS = frozenset(
    {
        "future",
        "post_event",
        "label",
        "target",
        "outcome",
        "prediction",
        "future_return",
        "label_return",
        "post_event_score",
        "future_ret",
        "fwd_return",
        "forward_return",
    }
)


def _reject_unsafe_strict_fields(value: Any, path: str = "payload") -> None:
    """Reject unsafe extension keys recursively before strict normalization.

    ``_validate_physical_input`` validates the six source pools, while this
    boundary validates the caller's aggregate proposal.  Both initial and
    successor publication call it before the proposal is normalized, so an
    unknown nested field cannot disappear silently and become an apparently
    authoritative artifact.
    """

    if isinstance(value, Mapping):
        for key, nested in value.items():
            folded = str(key).casefold().replace("-", "_")
            if folded in _STRICT_SAFE_FLAG_KEYS:
                # The strict artifact requires these flags and checks their
                # value separately.  They are not executable action fields.
                _reject_unsafe_strict_fields(nested, f"{path}.{key}")
                continue
            if folded in _STRICT_ACTION_KEYS or (
                folded != "trade_date"
                and (
                    folded.startswith(("buy_", "sell_", "order_", "trade_"))
                    or folded.endswith(("_buy", "_sell", "_order", "_trade"))
                )
            ):
                raise StrictCommitError(f"strict artifact unsafe action field: {path}.{key}")
            if (
                folded in _STRICT_OUTCOME_KEYS
                or folded.startswith("future_")
                or folded.startswith("post_event_")
                or folded.startswith("label_")
                or folded.startswith("target_")
                or folded.endswith("_future")
                or folded.endswith("_outcome")
                or folded.endswith("_label")
                or "post_event" in folded
                or "postevent" in folded
                or "future" in folded
                or "label" in folded
                or "outcome" in folded
                or "prediction" in folded
            ):
                raise StrictCommitError(
                    f"strict artifact unsafe outcome field: {path}.{key}"
                )
            _reject_unsafe_strict_fields(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_unsafe_strict_fields(nested, f"{path}[{index}]")


class StrictCommitError(ValueError):
    """A strict chain is absent, malformed, conflicting, or not promotable."""


@dataclass(frozen=True, slots=True)
class EvidenceIdentity:
    owner_id: str
    producer_id: str
    release_id: str
    lane_id: str

    def validate(self) -> None:
        for name in ("owner_id", "producer_id", "release_id", "lane_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise StrictCommitError(f"evidence identity {name} is missing")
            if any(token in value for token in ("/", "\\", "\x00")):
                raise StrictCommitError(f"evidence identity {name} is unsafe")
        if self.owner_id != _OWNER:
            raise StrictCommitError("evidence identity owner_id mismatch")
        if self.producer_id != _PRODUCER:
            raise StrictCommitError("evidence identity producer_id mismatch")
        if self.lane_id != _LANE:
            raise StrictCommitError("evidence identity lane_id mismatch")

    def as_dict(self) -> dict[str, str]:
        self.validate()
        return {
            "owner_id": self.owner_id,
            "producer_id": self.producer_id,
            "release_id": self.release_id,
            "lane_id": self.lane_id,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EvidenceIdentity":
        if not isinstance(value, Mapping):
            raise StrictCommitError("evidence identity must be an object")
        identity = cls(
            owner_id=value.get("owner_id", ""),
            producer_id=value.get("producer_id", ""),
            release_id=value.get("release_id", ""),
            lane_id=value.get("lane_id", ""),
        )
        identity.validate()
        return identity


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _raw_sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise StrictCommitError(f"{label} must be a SHA-256")
    return value


def _safe_date(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{8}", value):
        raise StrictCommitError("trade_date must be YYYYMMDD")
    return value


def _safe_run(value: Any) -> str:
    if not isinstance(value, str) or _RUN.fullmatch(value) is None:
        raise StrictCommitError("run_id must be a safe slug")
    return value


def _false_flags(payload: Mapping[str, Any], label: str) -> None:
    for name in _FLAGS:
        if name not in payload or payload[name] is not False:
            raise StrictCommitError(f"{label} safety flags must be false")


def _identity_fields(identity: EvidenceIdentity) -> dict[str, str]:
    return identity.as_dict()


def _check_identity(payload: Mapping[str, Any], identity: EvidenceIdentity, label: str) -> None:
    expected = _identity_fields(identity)
    if any(payload.get(name) != value for name, value in expected.items()):
        raise StrictCommitError(f"{label} evidence identity mismatch")


def _require_nonempty_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise StrictCommitError(f"{label} is missing")
    return value


def _validate_lineage_predecessor(
    predecessor: Mapping[str, Any], trade_date: str, identity: EvidenceIdentity
) -> None:
    if not isinstance(predecessor, Mapping) or predecessor.get("trade_date") != trade_date:
        raise StrictCommitError("strict predecessor lineage/date is invalid")
    _safe_run(predecessor.get("run_id"))
    if predecessor.get("role") != STRICT_ROLE or predecessor.get("status") not in {"READY", "READY_EMPTY"}:
        raise StrictCommitError("strict predecessor identity/status is invalid")
    for field in (
        "commit_id", "current_bytes_sha256", "artifact_bytes_sha256",
        "artifact_canonical_sha256", "manifest_bytes_sha256",
        "manifest_canonical_sha256", "receipt_bytes_sha256",
        "receipt_canonical_sha256",
    ):
        _require_sha(predecessor.get(field), f"strict predecessor {field}")
    if not isinstance(predecessor.get("row_count"), int) or isinstance(predecessor.get("row_count"), bool) or predecessor["row_count"] < 0:
        raise StrictCommitError("strict predecessor row_count is invalid")
    _check_identity(predecessor, identity, "strict predecessor")
    _false_flags(predecessor, "strict predecessor")


def _validate_marker_supersession(
    supersession: Mapping[str, Any], trade_date: str, identity: EvidenceIdentity
) -> None:
    if not isinstance(supersession, Mapping):
        raise StrictCommitError("strict commit marker supersession is invalid")
    relative = _require_nonempty_text(supersession.get("relative"), "strict supersession path")
    if not relative.startswith(f"supersessions/{trade_date}/{STRICT_ROLE}/"):
        raise StrictCommitError("strict commit marker supersession path mismatch")
    _require_sha(supersession.get("expected_current_bytes_sha256"), "strict marker current SHA")
    _require_sha(supersession.get("successor_artifact_canonical_sha256"), "strict marker artifact SHA")
    _safe_run(supersession.get("successor_run_id"))
    _require_nonempty_text(supersession.get("reason"), "strict marker supersession reason")
    if supersession.get("evolution") != STRICT_SUCCESSOR_EVOLUTION:
        raise StrictCommitError("strict marker supersession evolution is invalid")
    target_current = _paths(trade_date, "placeholder")["current"]
    if (
        supersession.get("target_current_relative") != target_current
        or supersession.get("successor_current_relative") != target_current
    ):
        raise StrictCommitError("strict marker supersession target path mismatch")
    if "owner_id" in supersession:
        _check_identity(supersession, identity, "strict marker supersession")


_POOL_BINDING_FIELDS = (
    "pool_id",
    "status",
    "producer_id",
    "source_role",
    "source_merge_role",
    "stage_selection_eligible",
    "raw_row_count",
    "row_count",
    "valid_empty",
    "available",
    "diagnostics",
    "pool_sha256",
    "artifact_raw_sha256",
    "manifest_raw_sha256",
    "receipt_raw_sha256",
    "artifact_relative_path",
    "manifest_relative_path",
    "receipt_relative_path",
)


def _physical_pool_provenance(snapshot: StrictAPreselectionSnapshot) -> list[dict[str, Any]]:
    """Return the publication provenance owned by one physical snapshot."""

    return snapshot_pool_provenance(snapshot)


def _validate_physical_input(
    payload: Mapping[str, Any], snapshot: StrictAPreselectionSnapshot
) -> None:
    """Bind the caller's V2/V3 projection to a fresh physical six-pool read.

    The Gate2 builder emits a V2-shaped object even when its source is a strict
    physical snapshot.  Validate that object before adding V3 identity fields;
    then validate every physical provenance field explicitly so optional V3
    extensions cannot be silently substituted while calling the shared pure
    contract validator.
    """

    if not isinstance(payload, Mapping):
        raise StageAcquisitionContractError("stage-acquisition artifact is not an object")
    expected = _physical_pool_provenance(snapshot)
    actual = payload.get("source_pool_provenance")
    if not isinstance(actual, list) or len(actual) != len(expected):
        raise StageAcquisitionContractError("stage-acquisition source pool provenance is incomplete")
    for index, (item, expected_item) in enumerate(zip(actual, expected)):
        if not isinstance(item, Mapping):
            raise StageAcquisitionContractError("stage-acquisition source pool provenance is invalid")
        for field in _POOL_BINDING_FIELDS:
            if item.get(field) != expected_item[field]:
                raise StageAcquisitionContractError(
                    f"stage-acquisition source pool {expected_item['pool_id']} {field} binding mismatch"
                )
        for field in ("producer_id", "source_role", "valid_empty"):
            if field in item and item.get(field) != expected_item[field]:
                raise StageAcquisitionContractError(
                    f"stage-acquisition source pool {expected_item['pool_id']} {field} binding mismatch"
                )

    # The shared validator is the authority for the aggregate codes, source
    # order, exact-date and policy bindings.  Preserve the source-only lane
    # markers because the zero-contribution contract is bound to them.
    comparison = dict(payload)
    comparison["source_pool_provenance"] = [
        {field: item[field] for field in _POOL_BINDING_FIELDS}
        for item in actual
    ]
    comparison["source_pool_provenance_sha256"] = _canonical_sha(
        comparison["source_pool_provenance"]
    )
    validate_artifact_against_snapshot(comparison, snapshot)


def _normalize_strict_artifact(
    payload: Mapping[str, Any],
    snapshot: StrictAPreselectionSnapshot,
    identity: EvidenceIdentity,
) -> dict[str, Any]:
    """Copy a verified Gate2 artifact into the strict V3 wire schema."""

    artifact = dict(payload)
    if artifact.get("trade_date") != snapshot.trade_date:
        raise StrictCommitError("strict artifact trade_date mismatch")
    accepted = {
        "schema_version": {"A_SHARE_STAGE_ACQUISITION_UNIVERSE_V2", STRICT_ARTIFACT_SCHEMA},
        "artifact_role": {"A_SHARE_STAGE_ACQUISITION_UNIVERSE_V2", STRICT_ROLE},
        "artifact_version": {"V2", STRICT_ARTIFACT_VERSION},
        "source_merge_role": {"STAGE_ACQUISITION_INPUT"},
    }
    for field, values in accepted.items():
        if field in artifact and artifact[field] not in values:
            raise StrictCommitError(f"strict artifact {field} mismatch")
    if "stage_selection_eligible" in artifact and artifact["stage_selection_eligible"] is not True:
        raise StrictCommitError("strict artifact stage role is invalid")
    expected_identity = _identity_fields(identity)
    if any(
        field in artifact and artifact[field] != value
        for field, value in expected_identity.items()
    ):
        raise StrictCommitError("strict artifact evidence identity mismatch")
    artifact.update(
        {
            "schema_version": STRICT_ARTIFACT_SCHEMA,
            "artifact_role": STRICT_ROLE,
            "artifact_version": STRICT_ARTIFACT_VERSION,
            "authority": "STRICT_PHYSICAL_POOL_SNAPSHOT",
            **expected_identity,
        }
    )
    artifact["source_pool_provenance"] = _physical_pool_provenance(snapshot)
    artifact["source_pool_provenance_sha256"] = _canonical_sha(
        artifact["source_pool_provenance"]
    )
    artifact["cannot_confirm"] = list(snapshot.diagnostic_reasons)
    artifact["blocking_reasons"] = []
    artifact["pool_diagnostics"] = {
        pool_id: list(reasons)
        for pool_id, reasons in snapshot.pool_diagnostics.items()
    }
    artifact["known_pool_ids"] = list(snapshot.known_pool_ids)
    artifact["available_pool_ids"] = list(snapshot.pool_ids)
    return artifact


def _pool_value(item: Mapping[str, Any], primary: str, alias: str, label: str) -> str:
    value = item.get(primary, item.get(alias))
    return _require_sha(value, label)


def _validate_artifact(payload: Mapping[str, Any], trade_date: str, identity: EvidenceIdentity) -> None:
    if not isinstance(payload, Mapping):
        raise StrictCommitError("strict artifact must be an object")
    if payload.get("schema_version") != STRICT_ARTIFACT_SCHEMA or payload.get("artifact_role") != STRICT_ROLE:
        raise StrictCommitError("strict artifact schema or role mismatch")
    if payload.get("artifact_version") != STRICT_ARTIFACT_VERSION:
        raise StrictCommitError("strict artifact version mismatch")
    if payload.get("authority") != "STRICT_PHYSICAL_POOL_SNAPSHOT":
        raise StrictCommitError("strict artifact authority mismatch")
    if payload.get("trade_date") != trade_date:
        raise StrictCommitError("strict artifact trade_date mismatch")
    if payload.get("status") not in {"READY", "READY_EMPTY"}:
        raise StrictCommitError("strict artifact status is not ready")
    _check_identity(payload, identity, "strict artifact")
    _false_flags(payload, "strict artifact")
    if payload.get("source_merge_role") != "STAGE_ACQUISITION_INPUT" or payload.get("stage_selection_eligible") is not True:
        raise StrictCommitError("strict artifact stage role is invalid")
    cannot_confirm = payload.get("cannot_confirm", [])
    if not isinstance(cannot_confirm, list) or any(
        not isinstance(item, str) for item in cannot_confirm
    ):
        raise StrictCommitError("strict artifact cannot_confirm is invalid")
    blocking_reasons = payload.get("blocking_reasons", [])
    if not isinstance(blocking_reasons, list) or any(
        not isinstance(item, str) for item in blocking_reasons
    ) or blocking_reasons:
        raise StrictCommitError("strict artifact blocking_reasons must be empty")
    pool_diagnostics = payload.get("pool_diagnostics", {})
    if not isinstance(pool_diagnostics, Mapping):
        raise StrictCommitError("strict artifact pool_diagnostics is invalid")
    flattened_diagnostics: list[str] = []
    for pool_id in REQUIRED_A_STAGE_POOL_IDS:
        reasons = pool_diagnostics.get(pool_id, [])
        if not isinstance(reasons, list) or any(
            not isinstance(reason, str) for reason in reasons
        ):
            raise StrictCommitError(
                f"strict artifact pool {pool_id} diagnostics are invalid"
            )
        flattened_diagnostics.extend(f"{pool_id}:{reason}" for reason in reasons)
    if cannot_confirm != flattened_diagnostics:
        raise StrictCommitError("strict artifact diagnostics are not bound")
    notes = payload.get("policy_notes")
    if not isinstance(notes, list) or any(not isinstance(item, str) for item in notes):
        raise StrictCommitError("strict artifact policy_notes are invalid")

    codes = payload.get("codes")
    if not isinstance(codes, list) or any(not isinstance(code, str) or _CODE.fullmatch(code) is None for code in codes):
        raise StrictCommitError("strict artifact codes are invalid")
    if len(codes) != len(set(codes)):
        raise StrictCommitError("strict artifact codes contain duplicates")
    if payload["status"] == "READY" and not codes:
        raise StrictCommitError("strict READY artifact has no codes")
    if payload["status"] == "READY_EMPTY" and codes:
        raise StrictCommitError("strict READY_EMPTY artifact has codes")
    if payload.get("row_count") != len(codes) or isinstance(payload.get("row_count"), bool):
        raise StrictCommitError("strict artifact row_count mismatch")
    if payload.get("codes_sha256") != _canonical_sha(codes):
        raise StrictCommitError("strict artifact codes SHA mismatch")
    _require_sha(payload.get("source_projection_sha256"), "strict artifact source_projection_sha256")
    if payload.get("source_projection_row_count") != len(codes):
        raise StrictCommitError("strict artifact source row_count mismatch")
    if payload.get("source_projection_status") not in {"READY_WITH_ROWS", "READY_EMPTY"}:
        raise StrictCommitError("strict artifact source status mismatch")

    provenance = payload.get("source_pool_provenance")
    if not isinstance(provenance, list) or tuple(item.get("pool_id") if isinstance(item, Mapping) else None for item in provenance) != REQUIRED_A_STAGE_POOL_IDS:
        raise StrictCommitError("strict artifact source-pool set mismatch")
    for item in provenance:
        if not isinstance(item, Mapping):
            raise StrictCommitError("strict artifact source-pool provenance is invalid")
        pool_id = item["pool_id"]
        available = item.get("available", True)
        if not isinstance(available, bool):
            raise StrictCommitError("strict artifact source-pool availability is invalid")
        count = item.get("row_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise StrictCommitError("strict artifact source-pool row_count is invalid")
        empty = item.get("valid_empty", False)
        if not isinstance(empty, bool) or (
            available and empty != (count == 0)
        ) or (not available and empty):
            raise StrictCommitError("strict artifact source-pool empty marker is invalid")
        diagnostics = item.get("diagnostics", [])
        if not isinstance(diagnostics, list) or any(
            not isinstance(reason, str) for reason in diagnostics
        ):
            raise StrictCommitError("strict artifact source-pool diagnostics are invalid")
        if not available:
            if item.get("status") != "UNAVAILABLE" or count != 0 or empty:
                raise StrictCommitError("strict artifact unavailable source-pool binding is invalid")
            if item.get("producer_id") != "" or item.get("source_role") != "":
                raise StrictCommitError("strict artifact unavailable source-pool identity is invalid")
            if not diagnostics:
                raise StrictCommitError("strict artifact unavailable source-pool diagnostic is missing")
            for name in ("pool_sha256", "artifact_raw_sha256", "manifest_raw_sha256", "receipt_raw_sha256"):
                if item.get(name) is not None:
                    raise StrictCommitError(
                        f"strict artifact unavailable source-pool {pool_id} {name} must be null"
                    )
        else:
            expected_status = a_pool_contract(pool_id)[0]
            diagnostic_statuses = {
                "CANNOT_CONFIRM", "MISSING", "VALID_EMPTY", "FAILED",
                "SOURCE_MISSING", "NOT_MATERIALIZED", "UNAVAILABLE",
            }
            if count > 0 and item.get("status") != expected_status:
                raise StrictCommitError("strict artifact source-pool status is invalid")
            if (
                count == 0
                and item.get("status") != expected_status
                and item.get("status") not in diagnostic_statuses
                and not _is_non_contributing_source_only_lane(item, count, diagnostics)
            ):
                raise StrictCommitError("strict artifact empty source-pool status is invalid")
            if count == 0 and not diagnostics:
                raise StrictCommitError("strict artifact empty source-pool diagnostic is missing")
            if not isinstance(item.get("source_role", ""), str) or not item.get("source_role", ""):
                raise StrictCommitError("strict artifact source-pool source_role is missing")
            if not isinstance(item.get("producer_id", ""), str) or not item.get("producer_id", ""):
                raise StrictCommitError("strict artifact source-pool producer_id is missing")
            for name, alias in (("artifact_bytes_sha256", "artifact_raw_sha256"), ("manifest_bytes_sha256", "manifest_raw_sha256"), ("receipt_bytes_sha256", "receipt_raw_sha256"), ("pool_sha256", "semantic_sha256")):
                _pool_value(item, name, alias, f"strict artifact source-pool {pool_id} {name}")
        expected = {
            "artifact_relative_path": f"preselection_pools/{trade_date}/{pool_id}.json",
            "manifest_relative_path": f"preselection_pools/{trade_date}/manifest.json",
            "receipt_relative_path": f"preselection_pools/{trade_date}/receipts/{pool_id}.json",
        }
        if any(item.get(name) != path for name, path in expected.items()):
            raise StrictCommitError("strict artifact source-pool path mismatch")
    available_ids = payload.get("available_pool_ids")
    expected_available_ids = [
        item["pool_id"]
        for item in provenance
        if item.get("available", True) is True
    ]
    if available_ids is not None and available_ids != expected_available_ids:
        raise StrictCommitError("strict artifact available pool ordering mismatch")
    _require_sha(payload.get("source_pool_provenance_sha256"), "strict artifact source_pool_provenance_sha256")
    if payload["source_pool_provenance_sha256"] != _canonical_sha(provenance):
        raise StrictCommitError("strict artifact source-pool provenance SHA mismatch")
    sources = payload.get("code_sources")
    if not isinstance(sources, Mapping) or set(sources) != set(codes):
        raise StrictCommitError("strict artifact code source membership mismatch")
    for code in codes:
        values = sources.get(code)
        if not isinstance(values, list) or not values or any(pool_id not in REQUIRED_A_STAGE_POOL_IDS for pool_id in values) or len(values) != len(set(values)):
            raise StrictCommitError("strict artifact code source membership mismatch")
        provenance_by_pool = {
            item["pool_id"]: item for item in provenance if isinstance(item, Mapping)
        }
        if any(
            provenance_by_pool[pool_id].get("available", True) is not True
            or provenance_by_pool[pool_id].get("row_count", 0) <= 0
            for pool_id in values
        ):
            raise StrictCommitError("strict artifact code source is unavailable")


def _paths(trade_date: str, run_id: str) -> dict[str, str]:
    prefix = f"runs/{trade_date}/{STRICT_ROLE}/{run_id}"
    return {
        "artifact": f"{prefix}/artifact.json",
        "manifest": f"{prefix}/manifest.json",
        "receipt": f"{prefix}/receipt.json",
        "commit": f"{prefix}/commit.json",
        "current": f"current/{trade_date}/{STRICT_ROLE}/current.json",
    }


def _manifest(artifact: Mapping[str, Any], identity: EvidenceIdentity, date: str, run: str, artifact_raw: str, artifact_canonical: str, artifact_size: int) -> dict[str, Any]:
    return {
        "schema_version": STRICT_MANIFEST_SCHEMA,
        "role": STRICT_ROLE,
        "trade_date": date,
        "run_id": run,
        "status": artifact["status"],
        "row_count": artifact["row_count"],
        "codes_sha256": artifact["codes_sha256"],
        "source_pool_provenance_sha256": artifact["source_pool_provenance_sha256"],
        "artifact_relative": _paths(date, run)["artifact"],
        "artifact_bytes_sha256": artifact_raw,
        "artifact_canonical_sha256": artifact_canonical,
        "artifact_size_bytes": artifact_size,
        "digest_mode": DIGEST_MODE,
        **_identity_fields(identity),
        **{name: False for name in _FLAGS},
    }


def _receipt(artifact: Mapping[str, Any], manifest: Mapping[str, Any], identity: EvidenceIdentity, date: str, run: str, artifact_raw: str, artifact_canonical: str, manifest_raw: str, manifest_canonical: str, manifest_size: int) -> dict[str, Any]:
    paths = _paths(date, run)
    return {
        "schema_version": STRICT_RECEIPT_SCHEMA,
        "role": STRICT_ROLE,
        "trade_date": date,
        "run_id": run,
        "status": artifact["status"],
        "row_count": artifact["row_count"],
        "codes_sha256": artifact["codes_sha256"],
        "source_pool_provenance_sha256": artifact["source_pool_provenance_sha256"],
        "artifact_relative": paths["artifact"],
        "manifest_relative": paths["manifest"],
        "artifact_bytes_sha256": artifact_raw,
        "artifact_canonical_sha256": artifact_canonical,
        "manifest_bytes_sha256": manifest_raw,
        "manifest_canonical_sha256": manifest_canonical,
        "manifest_size_bytes": manifest_size,
        "digest_mode": DIGEST_MODE,
        **_identity_fields(identity),
        **{name: False for name in _FLAGS},
    }


def _commit_preimage(
    artifact: Mapping[str, Any],
    manifest: Mapping[str, Any],
    receipt: Mapping[str, Any],
    identity: EvidenceIdentity,
    date: str,
    run: str,
    hashes: Mapping[str, Any],
    *,
    predecessor: Mapping[str, Any] | None = None,
    supersession: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    paths = _paths(date, run)
    return {
        "schema_version": STRICT_COMMIT_SCHEMA,
        "role": STRICT_ROLE,
        "trade_date": date,
        "run_id": run,
        "status": COMMIT_STATUS,
        "artifact_relative": paths["artifact"],
        "manifest_relative": paths["manifest"],
        "receipt_relative": paths["receipt"],
        "current_relative": paths["current"],
        "artifact_bytes_sha256": hashes["artifact_bytes_sha256"],
        "artifact_canonical_sha256": hashes["artifact_canonical_sha256"],
        "manifest_bytes_sha256": hashes["manifest_bytes_sha256"],
        "manifest_canonical_sha256": hashes["manifest_canonical_sha256"],
        "receipt_bytes_sha256": hashes["receipt_bytes_sha256"],
        "receipt_canonical_sha256": hashes["receipt_canonical_sha256"],
        "predecessor": dict(predecessor) if predecessor is not None else None,
        "supersession": dict(supersession) if supersession is not None else None,
        "digest_mode": DIGEST_MODE,
        **_identity_fields(identity),
        **{name: False for name in _FLAGS},
    }


def _current(
    artifact: Mapping[str, Any],
    identity: EvidenceIdentity,
    date: str,
    run: str,
    hashes: Mapping[str, Any],
    commit_id: str,
    marker_raw: str,
    marker_canonical: str,
    marker_size: int,
    *,
    predecessor: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    paths = _paths(date, run)
    return {
        "schema_version": STRICT_CURRENT_SCHEMA,
        "role": STRICT_ROLE,
        "trade_date": date,
        "run_id": run,
        "status": artifact["status"],
        "row_count": artifact["row_count"],
        "codes_sha256": artifact["codes_sha256"],
        "source_pool_provenance_sha256": artifact["source_pool_provenance_sha256"],
        "artifact_relative": paths["artifact"],
        "manifest_relative": paths["manifest"],
        "receipt_relative": paths["receipt"],
        "commit_marker_relative": paths["commit"],
        "artifact_bytes_sha256": hashes["artifact_bytes_sha256"],
        "artifact_canonical_sha256": hashes["artifact_canonical_sha256"],
        "manifest_bytes_sha256": hashes["manifest_bytes_sha256"],
        "manifest_canonical_sha256": hashes["manifest_canonical_sha256"],
        "receipt_bytes_sha256": hashes["receipt_bytes_sha256"],
        "receipt_canonical_sha256": hashes["receipt_canonical_sha256"],
        "commit_id": commit_id,
        "commit_marker_bytes_sha256": marker_raw,
        "commit_marker_canonical_sha256": marker_canonical,
        "commit_marker_size_bytes": marker_size,
        "previous_commit_id": (
            predecessor.get("commit_id") if predecessor is not None else None
        ),
        "previous_current_bytes_sha256": (
            predecessor.get("current_bytes_sha256") if predecessor is not None else None
        ),
        "predecessor": dict(predecessor) if predecessor is not None else None,
        "digest_mode": DIGEST_MODE,
        **_identity_fields(identity),
        **{name: False for name in _FLAGS},
    }


def _decode(result: ReadBytesResult, label: str) -> dict[str, Any]:
    try:
        value = json.loads(result.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StrictCommitError(f"{label} cannot be decoded") from error
    if not isinstance(value, dict) or result.data != _canonical_bytes(value):
        raise StrictCommitError(f"{label} bytes are not canonical")
    return value


def _close_fd(secure: SecureEvidenceRoot, fd: int, root_fd: int) -> None:
    if fd != root_fd:
        try:
            import os
            os.close(fd)
        except OSError:
            pass


def _revalidate_physical_snapshot(
    root: Path, trade_date: str, expected: StrictAPreselectionSnapshot
) -> None:
    """Refuse publication if physical pool evidence changed before the lock.

    The first snapshot is needed to build the caller's proposal.  A fresh
    snapshot inside the import lock is the publication gate: pool writers use
    that same lock, so the verified source cannot change between this check and
    the commit writes.
    """

    try:
        current = read_strict_a_preselection_snapshot(root, trade_date)
    except (StageAcquisitionContractError, OSError, ValueError) as error:
        raise StrictCommitError(
            f"required A pool strict physical snapshot cannot be confirmed while locked: {error}"
        ) from error
    if current != expected:
        raise StrictCommitError(
            "strict physical pool snapshot changed before publication"
        )


class StageAcquisitionUniverseCommit:
    """Writer and verifier for one strict exact-date candidate release."""

    def __init__(self, root: Path | str, *, max_file_bytes: int = _MAX_BYTES) -> None:
        self.root = Path(root)
        self.max_file_bytes = max_file_bytes

    def _secure(self) -> SecureEvidenceRoot:
        return SecureEvidenceRoot(self.root, max_file_bytes=self.max_file_bytes)

    @staticmethod
    def _write(secure: SecureEvidenceRoot, relative: str, value: Mapping[str, Any]) -> str:
        try:
            return secure.create_immutable_bytes(relative, _canonical_bytes(value))
        except (SecureEvidenceConflict, SecureEvidenceUnavailable) as error:
            raise StrictCommitError(str(error)) from error

    @staticmethod
    def _fsync_run_dir(secure: SecureEvidenceRoot, date: str, run: str) -> None:
        import os
        parts = tuple(_paths(date, run)["artifact"].split("/")[:-1])
        parent_fd = secure._open_parent((*parts, ".directory"))
        root_fd = secure._assert_open()
        try:
            secure._fsync_directory(parent_fd)
        finally:
            _close_fd(secure, parent_fd, root_fd)

    def _verify_run(self, secure: SecureEvidenceRoot, date: str, run: str, identity: EvidenceIdentity) -> dict[str, Any]:
        paths = _paths(date, run)
        try:
            artifact_result = secure.read_regular_bytes(paths["artifact"])
            manifest_result = secure.read_regular_bytes(paths["manifest"])
            receipt_result = secure.read_regular_bytes(paths["receipt"])
            marker_result = secure.read_regular_bytes(paths["commit"])
        except (SecureEvidenceUnavailable, SecureEvidenceConflict) as error:
            raise StrictCommitError("strict committed run evidence or marker is unavailable") from error
        artifact = _decode(artifact_result, "strict artifact")
        manifest = _decode(manifest_result, "strict manifest")
        receipt = _decode(receipt_result, "strict receipt")
        marker = _decode(marker_result, "strict commit marker")
        _validate_artifact(artifact, date, identity)
        hashes = {
            "artifact_bytes_sha256": artifact_result.sha256,
            "artifact_canonical_sha256": _canonical_sha(artifact),
            "manifest_bytes_sha256": manifest_result.sha256,
            "manifest_canonical_sha256": _canonical_sha(manifest),
            "receipt_bytes_sha256": receipt_result.sha256,
            "receipt_canonical_sha256": _canonical_sha(receipt),
        }
        if manifest != _manifest(artifact, identity, date, run, artifact_result.sha256, hashes["artifact_canonical_sha256"], artifact_result.size):
            raise StrictCommitError("strict manifest binding mismatch")
        if receipt != _receipt(artifact, manifest, identity, date, run, artifact_result.sha256, hashes["artifact_canonical_sha256"], manifest_result.sha256, hashes["manifest_canonical_sha256"], manifest_result.size):
            raise StrictCommitError("strict receipt binding mismatch")
        marker_predecessor = marker.get("predecessor")
        marker_supersession = marker.get("supersession")
        if marker_predecessor is not None:
            _validate_lineage_predecessor(marker_predecessor, date, identity)
        if marker_supersession is not None:
            _validate_marker_supersession(marker_supersession, date, identity)
        expected_marker_preimage = _commit_preimage(
            artifact,
            manifest,
            receipt,
            identity,
            date,
            run,
            hashes,
            predecessor=marker_predecessor,
            supersession=marker_supersession,
        )
        expected_marker = {**expected_marker_preimage, "commit_id": _canonical_sha(expected_marker_preimage)}
        if marker != expected_marker:
            raise StrictCommitError("strict commit marker binding mismatch")
        result = {
            "trade_date": date,
            "run_id": run,
            "artifact": artifact,
            "manifest": manifest,
            "receipt": receipt,
            "commit": marker,
            "artifact_path": self.root / paths["artifact"],
            "manifest_path": self.root / paths["manifest"],
            "receipt_path": self.root / paths["receipt"],
            "commit_marker_path": self.root / paths["commit"],
            "artifact_bytes_sha256": artifact_result.sha256,
            "artifact_canonical_sha256": hashes["artifact_canonical_sha256"],
            "manifest_bytes_sha256": manifest_result.sha256,
            "manifest_canonical_sha256": hashes["manifest_canonical_sha256"],
            "receipt_bytes_sha256": receipt_result.sha256,
            "receipt_canonical_sha256": hashes["receipt_canonical_sha256"],
            "commit_id": marker["commit_id"],
            "commit_marker_bytes_sha256": marker_result.sha256,
            "commit_marker_canonical_sha256": _canonical_sha(marker),
            "commit_marker_size_bytes": marker_result.size,
        }
        return result

    def _verify_current(self, secure: SecureEvidenceRoot, date: str, identity: EvidenceIdentity, expected: str | None = None) -> dict[str, Any]:
        paths = _paths(date, "placeholder")
        current_relative = paths["current"]
        try:
            current_result = secure.read_regular_bytes(current_relative)
        except SecureEvidenceUnavailable as error:
            raise StrictCommitError("strict current is missing or unavailable") from error
        if expected is not None and current_result.sha256 != expected:
            raise StrictCommitError("strict current raw SHA mismatch")
        current = _decode(current_result, "strict current")
        if current.get("schema_version") != STRICT_CURRENT_SCHEMA or current.get("role") != STRICT_ROLE or current.get("trade_date") != date or current.get("status") not in {"READY", "READY_EMPTY"}:
            raise StrictCommitError("strict current identity/status mismatch")
        _check_identity(current, identity, "strict current")
        _false_flags(current, "strict current")
        if current.get("digest_mode") != DIGEST_MODE:
            raise StrictCommitError("strict current digest mode is invalid")
        current_predecessor = current.get("predecessor")
        previous_commit_id = current.get("previous_commit_id")
        previous_current_sha = current.get("previous_current_bytes_sha256")
        if (current_predecessor is None) != (
            previous_commit_id is None and previous_current_sha is None
        ):
            raise StrictCommitError("strict current predecessor fields are incomplete")
        run = _safe_run(current.get("run_id"))
        chain = self._verify_run(secure, date, run, identity)
        marker_predecessor = chain["commit"].get("predecessor")
        if marker_predecessor is not None:
            _validate_lineage_predecessor(marker_predecessor, date, identity)
        expected_current = _current(chain["artifact"], identity, date, run, {
            "artifact_bytes_sha256": chain["artifact_bytes_sha256"],
            "artifact_canonical_sha256": chain["artifact_canonical_sha256"],
            "manifest_bytes_sha256": chain["manifest_bytes_sha256"],
            "manifest_canonical_sha256": chain["manifest_canonical_sha256"],
            "receipt_bytes_sha256": chain["receipt_bytes_sha256"],
            "receipt_canonical_sha256": chain["receipt_canonical_sha256"],
        }, chain["commit_id"], chain["commit_marker_bytes_sha256"], chain["commit_marker_canonical_sha256"], chain["commit_marker_size_bytes"], predecessor=marker_predecessor)
        if current != expected_current:
            raise StrictCommitError("strict current binding mismatch")
        marker_supersession = chain["commit"].get("supersession")
        if marker_predecessor is None:
            if marker_supersession is not None:
                raise StrictCommitError("strict initial current has supersession lineage")
        else:
            self._verify_supersession_for_current(
                secure,
                date,
                identity,
                chain,
                current,
                current_result.sha256,
                marker_predecessor,
                marker_supersession,
            )
        return {**chain, "current": current, "current_path": self.root / current_relative, "current_bytes_sha256": current_result.sha256, "current_size_bytes": current_result.size}

    @staticmethod
    def _supersession_relative(
        date: str, expected_current_sha256: str, successor_artifact_canonical_sha256: str
    ) -> str:
        _require_sha(expected_current_sha256, "strict supersession expected current SHA")
        _require_sha(
            successor_artifact_canonical_sha256,
            "strict supersession successor artifact SHA",
        )
        return (
            f"supersessions/{date}/{STRICT_ROLE}/"
            f"{expected_current_sha256}-{successor_artifact_canonical_sha256}/receipt.json"
        )

    @staticmethod
    def _predecessor_summary(
        chain: Mapping[str, Any], current_sha256: str
    ) -> dict[str, Any]:
        current = chain["current"]
        return {
            "schema_version": STRICT_CURRENT_SCHEMA,
            "role": STRICT_ROLE,
            "trade_date": chain["trade_date"],
            "run_id": chain["run_id"],
            "status": current["status"],
            "row_count": current["row_count"],
            "codes_sha256": current["codes_sha256"],
            "source_projection_sha256": chain["artifact"]["source_projection_sha256"],
            "artifact_bytes_sha256": chain["artifact_bytes_sha256"],
            "artifact_canonical_sha256": chain["artifact_canonical_sha256"],
            "manifest_bytes_sha256": chain["manifest_bytes_sha256"],
            "manifest_canonical_sha256": chain["manifest_canonical_sha256"],
            "receipt_bytes_sha256": chain["receipt_bytes_sha256"],
            "receipt_canonical_sha256": chain["receipt_canonical_sha256"],
            "commit_id": chain["commit_id"],
            "commit_marker_bytes_sha256": chain["commit_marker_bytes_sha256"],
            "commit_marker_canonical_sha256": chain["commit_marker_canonical_sha256"],
            "current_bytes_sha256": current_sha256,
            **_identity_fields(
                EvidenceIdentity(
                    owner_id=current["owner_id"],
                    producer_id=current["producer_id"],
                    release_id=current["release_id"],
                    lane_id=current["lane_id"],
                )
            ),
            **{name: False for name in _FLAGS},
        }

    @staticmethod
    def _successor_lineage(chain: Mapping[str, Any]) -> dict[str, Any]:
        artifact = chain["artifact"]
        return {
            "run_id": chain["run_id"],
            "row_count": artifact["row_count"],
            "codes_sha256": artifact["codes_sha256"],
            "source_projection_sha256": artifact["source_projection_sha256"],
            "artifact_bytes_sha256": chain["artifact_bytes_sha256"],
            "artifact_canonical_sha256": chain["artifact_canonical_sha256"],
            "manifest_bytes_sha256": chain["manifest_bytes_sha256"],
            "manifest_canonical_sha256": chain["manifest_canonical_sha256"],
            "receipt_bytes_sha256": chain["receipt_bytes_sha256"],
            "receipt_canonical_sha256": chain["receipt_canonical_sha256"],
            "commit_id": chain["commit_id"],
            "commit_marker_bytes_sha256": chain["commit_marker_bytes_sha256"],
            "commit_marker_canonical_sha256": chain["commit_marker_canonical_sha256"],
        }

    @staticmethod
    def _chain_hashes(chain: Mapping[str, Any]) -> dict[str, str]:
        return {
            name: chain[name]
            for name in (
                "artifact_bytes_sha256",
                "artifact_canonical_sha256",
                "manifest_bytes_sha256",
                "manifest_canonical_sha256",
                "receipt_bytes_sha256",
                "receipt_canonical_sha256",
            )
        }

    @staticmethod
    def _current_from_chain(
        chain: Mapping[str, Any],
        identity: EvidenceIdentity,
        date: str,
        *,
        predecessor: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Rebuild a current pointer solely from its committed run chain."""

        marker_predecessor = chain["commit"].get("predecessor")
        if predecessor is None:
            predecessor = marker_predecessor
        elif marker_predecessor != dict(predecessor):
            raise StrictCommitError("strict chain predecessor pointer mismatch")
        return _current(
            chain["artifact"],
            identity,
            date,
            chain["run_id"],
            StageAcquisitionUniverseCommit._chain_hashes(chain),
            chain["commit_id"],
            chain["commit_marker_bytes_sha256"],
            chain["commit_marker_canonical_sha256"],
            chain["commit_marker_size_bytes"],
            predecessor=predecessor,
        )

    def _build_supersession_receipt(
        self,
        *,
        date: str,
        identity: EvidenceIdentity,
        reason: str,
        expected_current_sha256: str,
        predecessor: Mapping[str, Any],
        previous_current: Mapping[str, Any],
        successor_chain: Mapping[str, Any],
        successor_current: Mapping[str, Any],
        target_current_relative: str,
    ) -> dict[str, Any]:
        """Build the complete canonical receipt from the verified chain.

        Every field is derived from the predecessor/successor chain or the
        explicit request.  Readers use this same function, so a receipt field
        cannot be changed in place without failing canonical reconstruction.
        """

        expected = _require_sha(
            expected_current_sha256,
            "strict supersession expected current SHA",
        )
        reason_text = _require_nonempty_text(reason, "strict supersession reason")
        target = _require_nonempty_text(
            target_current_relative, "strict supersession target path"
        )
        predecessor_sha = _require_sha(
            predecessor.get("current_bytes_sha256"),
            "strict supersession predecessor current SHA",
        )
        if expected != predecessor_sha:
            raise StrictCommitError("strict supersession predecessor current SHA mismatch")
        successor_current_bytes = _canonical_bytes(successor_current)
        return {
            "schema_version": STRICT_SUPERSESSION_SCHEMA,
            "role": STRICT_ROLE,
            "trade_date": date,
            "status": "SUPERSEDED",
            "evolution": STRICT_SUCCESSOR_EVOLUTION,
            "reason": reason_text,
            "expected_current_bytes_sha256": expected,
            "previous_current_bytes_sha256": predecessor_sha,
            "previous_commit_id": predecessor["commit_id"],
            "predecessor": dict(predecessor),
            "previous_current": dict(previous_current),
            "successor_run_id": successor_chain["run_id"],
            "successor": self._successor_lineage(successor_chain),
            "successor_current": dict(successor_current),
            "successor_current_bytes_sha256": _raw_sha(successor_current_bytes),
            "target_current_relative": target,
            "successor_current_relative": target,
            **_identity_fields(identity),
            **{name: False for name in _FLAGS},
        }

    def _verify_supersession_for_current(
        self,
        secure: SecureEvidenceRoot,
        date: str,
        identity: EvidenceIdentity,
        chain: Mapping[str, Any],
        current: Mapping[str, Any],
        current_sha256: str,
        predecessor: Mapping[str, Any],
        marker_supersession: Mapping[str, Any] | None,
    ) -> None:
        """Verify the immutable receipt that explains a successor current."""

        if marker_supersession is None:
            raise StrictCommitError("strict successor current has no supersession receipt")
        _validate_marker_supersession(marker_supersession, date, identity)
        relative = marker_supersession["relative"]
        try:
            result = secure.read_regular_bytes(relative)
        except (SecureEvidenceUnavailable, SecureEvidenceConflict) as error:
            raise StrictCommitError("strict successor supersession receipt is unavailable") from error
        receipt = _decode(result, "strict supersession receipt")
        if marker_supersession.get("expected_current_bytes_sha256") != receipt.get(
            "expected_current_bytes_sha256"
        ):
            raise StrictCommitError("strict supersession marker CAS mismatch")
        if marker_supersession.get("successor_run_id") != chain["run_id"]:
            raise StrictCommitError("strict supersession marker run mismatch")
        if marker_supersession.get("successor_artifact_canonical_sha256") != chain[
            "artifact_canonical_sha256"
        ]:
            raise StrictCommitError("strict supersession marker artifact mismatch")
        if relative != self._supersession_relative(
            date,
            marker_supersession["expected_current_bytes_sha256"],
            chain["artifact_canonical_sha256"],
        ):
            raise StrictCommitError("strict supersession marker path mismatch")

        # Re-verify the predecessor run and rebuild its current pointer.  The
        # receipt's previous_current object is therefore committed by the
        # predecessor chain, rather than accepted merely because its own SHA
        # field happens to be self-consistent.
        predecessor_run = _safe_run(predecessor.get("run_id"))
        predecessor_chain = self._verify_run(secure, date, predecessor_run, identity)
        previous_current = self._current_from_chain(
            predecessor_chain, identity, date
        )
        if _raw_sha(_canonical_bytes(previous_current)) != predecessor[
            "current_bytes_sha256"
        ]:
            raise StrictCommitError("strict supersession previous current bytes mismatch")
        expected_predecessor = self._predecessor_summary(
            {**predecessor_chain, "current": previous_current},
            predecessor["current_bytes_sha256"],
        )
        if dict(predecessor) != expected_predecessor:
            raise StrictCommitError("strict supersession predecessor lineage mismatch")

        expected_receipt = self._build_supersession_receipt(
            date=date,
            identity=identity,
            reason=marker_supersession["reason"],
            expected_current_sha256=marker_supersession[
                "expected_current_bytes_sha256"
            ],
            predecessor=predecessor,
            previous_current=previous_current,
            successor_chain=chain,
            successor_current=current,
            target_current_relative=marker_supersession["target_current_relative"],
        )
        if receipt != expected_receipt:
            raise StrictCommitError(
                "strict supersession receipt canonical binding mismatch "
                "(successor current or request)"
            )
        if _raw_sha(_canonical_bytes(current)) != current_sha256:
            raise StrictCommitError("strict supersession successor current bytes mismatch")

    def _verify_supersession_for_predecessor(
        self,
        secure: SecureEvidenceRoot,
        date: str,
        identity: EvidenceIdentity,
        receipt: Mapping[str, Any],
        receipt_relative: str,
        predecessor_chain: Mapping[str, Any],
        expected_current_sha256: str,
        reason: str,
        requested_artifact_canonical_sha256: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Verify a receipt left before CAS so a safe retry can resume it."""

        if receipt.get("schema_version") != STRICT_SUPERSESSION_SCHEMA:
            raise StrictCommitError("strict supersession receipt schema mismatch")
        if receipt.get("role") != STRICT_ROLE or receipt.get("trade_date") != date:
            raise StrictCommitError("strict supersession receipt identity mismatch")
        if receipt.get("status") != "SUPERSEDED" or receipt.get("reason") != reason:
            raise StrictCommitError("strict supersession receipt request conflict")
        _check_identity(receipt, identity, "strict supersession receipt")
        _false_flags(receipt, "strict supersession receipt")
        predecessor_sha = predecessor_chain["current_bytes_sha256"]
        if receipt.get("expected_current_bytes_sha256") != expected_current_sha256 or receipt.get("previous_current_bytes_sha256") != predecessor_sha:
            raise StrictCommitError("strict supersession predecessor current SHA mismatch")
        predecessor = self._predecessor_summary(predecessor_chain, predecessor_sha)
        if receipt.get("previous_commit_id") != predecessor["commit_id"] or receipt.get("predecessor") != predecessor:
            raise StrictCommitError("strict supersession predecessor lineage mismatch")
        previous_current = predecessor_chain["current"]
        if _raw_sha(_canonical_bytes(previous_current)) != predecessor_sha:
            raise StrictCommitError("strict supersession previous current bytes mismatch")
        target_current = _paths(date, "placeholder")["current"]
        if (
            receipt.get("target_current_relative") != target_current
            or receipt.get("successor_current_relative") != target_current
            or receipt_relative != self._supersession_relative(
                date, expected_current_sha256, requested_artifact_canonical_sha256
            )
        ):
            raise StrictCommitError("strict supersession receipt path mismatch")
        successor_run = _safe_run(receipt.get("successor_run_id"))
        try:
            successor_chain = self._verify_run(secure, date, successor_run, identity)
        except StrictCommitError as error:
            raise StrictCommitError("strict supersession successor chain is unavailable") from error
        if successor_chain["artifact_canonical_sha256"] != requested_artifact_canonical_sha256:
            raise StrictCommitError("strict supersession successor artifact conflict")
        marker_supersession = successor_chain["commit"].get("supersession")
        if marker_supersession is None:
            raise StrictCommitError("strict supersession successor marker is missing")
        _validate_marker_supersession(marker_supersession, date, identity)
        if (
            marker_supersession.get("relative") != receipt_relative
            or marker_supersession.get("reason") != reason
            or marker_supersession.get("expected_current_bytes_sha256")
            != expected_current_sha256
            or marker_supersession.get("successor_artifact_canonical_sha256")
            != requested_artifact_canonical_sha256
            or marker_supersession.get("successor_run_id") != successor_run
        ):
            raise StrictCommitError("strict supersession marker request conflict")
        successor_current = self._current_from_chain(
            successor_chain,
            identity,
            date,
            predecessor=predecessor,
        )
        expected_receipt = self._build_supersession_receipt(
            date=date,
            identity=identity,
            reason=reason,
            expected_current_sha256=expected_current_sha256,
            predecessor=predecessor,
            previous_current=previous_current,
            successor_chain=successor_chain,
            successor_current=successor_current,
            target_current_relative=target_current,
        )
        if receipt != expected_receipt:
            raise StrictCommitError(
                "strict supersession receipt canonical binding mismatch "
                "(successor current or request)"
            )
        return successor_chain, successor_current


    def _run_root(self, date: str) -> Path:
        return self.root / f"runs/{date}/{STRICT_ROLE}"

    def _scan_orphans(self, secure: SecureEvidenceRoot, date: str, identity: EvidenceIdentity, selected_run: str) -> tuple[list[dict[str, Any]], bool]:
        root = self._run_root(date)
        if not root.exists():
            return [], False
        if root.is_symlink() or not root.is_dir():
            raise StrictCommitError("strict run root is unsafe")
        committed: list[dict[str, Any]] = []
        selected_partial = False
        for entry in sorted(root.iterdir(), key=lambda item: item.name):
            run = _safe_run(entry.name)
            if entry.is_symlink() or not entry.is_dir():
                raise StrictCommitError("strict run entry is unsafe")
            paths = _paths(date, run)
            present = [bool((self.root / paths[name]).exists()) for name in ("artifact", "manifest", "receipt", "commit")]
            if not any(present):
                raise StrictCommitError("strict run entry is empty")
            if present[3]:
                try:
                    committed.append(self._verify_run(secure, date, run, identity))
                except StrictCommitError as error:
                    raise StrictCommitError(f"strict orphan {run} is malformed: {error}") from error
            elif run == selected_run:
                selected_partial = True
            else:
                raise StrictCommitError(f"strict orphan {run} is incomplete")
        return committed, selected_partial

    def _recover_committed_successor_orphan(
        self,
        secure: SecureEvidenceRoot,
        date: str,
        identity: EvidenceIdentity,
        current: Mapping[str, Any],
        current_sha256: str,
        expected_current_sha256: str,
        artifact_canonical_sha256: str,
        reason: str,
        selected_run: str,
        supersession_relative: str,
    ) -> dict[str, Any] | None:
        """Resume one committed successor that stopped before receipt/CAS.

        The run marker is the durable boundary for a successor.  A retry first
        searches committed runs bound to the same predecessor raw-current
        SHA; it never creates a parallel run when exactly one such orphan is
        recoverable.  Multiple or conflicting matches are fail-closed.
        """

        committed, _selected_partial = self._scan_orphans(
            secure, date, identity, selected_run
        )
        current_successor_orphans: list[dict[str, Any]] = []
        for candidate in committed:
            marker_predecessor = candidate["commit"].get("predecessor")
            if marker_predecessor is None:
                continue
            if marker_predecessor.get("current_bytes_sha256") != current_sha256:
                continue
            if candidate["artifact_canonical_sha256"] != artifact_canonical_sha256:
                raise StrictCommitError(
                    "strict successor committed orphan conflicts with payload"
                )
            current_successor_orphans.append(candidate)

        if len(current_successor_orphans) > 1:
            raise StrictCommitError(
                "multiple strict successor committed orphans are ambiguous"
            )
        if not current_successor_orphans:
            return None

        orphan = current_successor_orphans[0]
        predecessor = self._predecessor_summary(current, current_sha256)
        if orphan["commit"].get("predecessor") != predecessor:
            raise StrictCommitError("strict successor orphan predecessor conflict")
        marker_supersession = orphan["commit"].get("supersession")
        if marker_supersession is None:
            raise StrictCommitError("strict successor orphan marker is incomplete")
        _validate_marker_supersession(marker_supersession, date, identity)
        if (
            marker_supersession.get("relative") != supersession_relative
            or marker_supersession.get("expected_current_bytes_sha256")
            != expected_current_sha256
            or marker_supersession.get("successor_artifact_canonical_sha256")
            != artifact_canonical_sha256
            or marker_supersession.get("successor_run_id") != orphan["run_id"]
            or marker_supersession.get("reason") != reason
        ):
            raise StrictCommitError("strict successor orphan request conflict")

        successor_pointer = self._current_from_chain(
            orphan,
            identity,
            date,
            predecessor=predecessor,
        )
        supersession = self._build_supersession_receipt(
            date=date,
            identity=identity,
            reason=reason,
            expected_current_sha256=expected_current_sha256,
            predecessor=predecessor,
            previous_current=current["current"],
            successor_chain=orphan,
            successor_current=successor_pointer,
            target_current_relative=_paths(date, "placeholder")["current"],
        )
        self._write(secure, supersession_relative, supersession)
        receipt_result = secure.read_regular_bytes(supersession_relative)
        receipt_check = _decode(receipt_result, "strict supersession receipt")
        if receipt_check != supersession:
            raise StrictCommitError("strict supersession receipt verification failed")
        secure.replace_current_cas(
            _paths(date, "placeholder")["current"],
            expected_current_bytes_sha256=current_sha256,
            new_bytes=_canonical_bytes(successor_pointer),
        )
        verified = self._verify_current(secure, date, identity)
        return self._successor_result(
            verified,
            supersession,
            self.root / supersession_relative,
            idempotent=True,
        )

    @staticmethod
    def _result(chain: Mapping[str, Any], *, idempotent: bool) -> dict[str, Any]:
        return {
            "status": chain["current"]["status"],
            "idempotent": idempotent,
            "trade_date": chain["trade_date"],
            "role": STRICT_ROLE,
            "run_id": chain["run_id"],
            "row_count": chain["current"]["row_count"],
            "artifact_bytes_sha256": chain["artifact_bytes_sha256"],
            "artifact_canonical_sha256": chain["artifact_canonical_sha256"],
            "manifest_bytes_sha256": chain["manifest_bytes_sha256"],
            "manifest_canonical_sha256": chain["manifest_canonical_sha256"],
            "receipt_bytes_sha256": chain["receipt_bytes_sha256"],
            "receipt_canonical_sha256": chain["receipt_canonical_sha256"],
            "commit_id": chain["commit_id"],
            "commit_marker_bytes_sha256": chain["commit_marker_bytes_sha256"],
            "commit_marker_canonical_sha256": chain["commit_marker_canonical_sha256"],
            "digest_mode": DIGEST_MODE,
            "artifact_path": chain["artifact_path"],
            "manifest_path": chain["manifest_path"],
            "receipt_path": chain["receipt_path"],
            "commit_marker_path": chain["commit_marker_path"],
            "current_path": chain["current_path"],
            "current_bytes_sha256": chain["current_bytes_sha256"],
            # Return the verified strict artifact to callers.  The Gate2 V2
            # input is never exposed as if it were the authoritative current.
            "artifact": dict(chain["artifact"]),
        }

    def publish(
        self,
        payload: Mapping[str, Any],
        *,
        run_id: str | None = None,
        identity: EvidenceIdentity | None = None,
    ) -> dict[str, Any]:
        if not isinstance(identity, EvidenceIdentity):
            raise StrictCommitError("strict publication requires evidence identity")
        identity.validate()
        _reject_unsafe_strict_fields(payload)
        date = _safe_date(payload.get("trade_date") if isinstance(payload, Mapping) else None)
        try:
            # This read is deliberately inside the strict writer, immediately
            # before any artifact bytes are computed or written.  A caller's
            # in-memory projection is therefore only a proposal; the six
            # physical pool trios remain the authority at publication time.
            snapshot = read_strict_a_preselection_snapshot(self.root, date)
            _validate_physical_input(payload, snapshot)
            artifact = _normalize_strict_artifact(payload, snapshot, identity)
        except (StageAcquisitionContractError, OSError, ValueError) as error:
            raise StrictCommitError(
                f"required A pool strict physical snapshot cannot be confirmed: {error}"
            ) from error
        _validate_artifact(artifact, date, identity)
        artifact_bytes = _canonical_bytes(artifact)
        artifact_canonical = _canonical_sha(artifact)
        selected_run = _safe_run(run_id or f"{date}-{STRICT_ROLE.lower()}-{artifact_canonical[:12]}")
        paths = _paths(date, selected_run)
        manifest = _manifest(artifact, identity, date, selected_run, _raw_sha(artifact_bytes), artifact_canonical, len(artifact_bytes))
        manifest_bytes = _canonical_bytes(manifest)
        manifest_canonical = _canonical_sha(manifest)
        receipt = _receipt(artifact, manifest, identity, date, selected_run, _raw_sha(artifact_bytes), artifact_canonical, _raw_sha(manifest_bytes), manifest_canonical, len(manifest_bytes))
        receipt_bytes = _canonical_bytes(receipt)
        lock = owned_interprocess_lock(
            self.root / ".import.lock",
            timeout_seconds=10,
            timeout_message="data-root import lock timeout",
        )
        try:
            with lock, self._secure() as secure:
                _revalidate_physical_snapshot(self.root, date, snapshot)
                try:
                    current = self._verify_current(secure, date, identity)
                except StrictCommitError as error:
                    if "missing or unavailable" not in str(error):
                        raise
                    current = None
                if current is not None:
                    if current["artifact_canonical_sha256"] == artifact_canonical and current["artifact"]["trade_date"] == date:
                        return self._result(current, idempotent=True)
                    raise StrictCommitError("strict exact-date current conflict")
                committed, _selected_partial = self._scan_orphans(secure, date, identity, selected_run)
                if len(committed) > 1:
                    raise StrictCommitError("multiple strict committed orphans are ambiguous")
                if committed:
                    orphan = committed[0]
                    if orphan["artifact_canonical_sha256"] != artifact_canonical:
                        raise StrictCommitError("strict committed orphan conflicts with payload")
                    hashes = {name: orphan[name] for name in ("artifact_bytes_sha256", "artifact_canonical_sha256", "manifest_bytes_sha256", "manifest_canonical_sha256", "receipt_bytes_sha256", "receipt_canonical_sha256")}
                    pointer = _current(orphan["artifact"], identity, date, orphan["run_id"], hashes, orphan["commit_id"], orphan["commit_marker_bytes_sha256"], orphan["commit_marker_canonical_sha256"], orphan["commit_marker_size_bytes"])
                    secure.replace_current_cas(_paths(date, orphan["run_id"])["current"], expected_current_bytes_sha256=None, new_bytes=_canonical_bytes(pointer))
                    verified = self._verify_current(secure, date, identity)
                    return self._result(verified, idempotent=True)

                self._write(secure, paths["artifact"], artifact)
                self._write(secure, paths["manifest"], manifest)
                self._write(secure, paths["receipt"], receipt)
                hashes = {
                    "artifact_bytes_sha256": _raw_sha(artifact_bytes),
                    "artifact_canonical_sha256": artifact_canonical,
                    "manifest_bytes_sha256": _raw_sha(manifest_bytes),
                    "manifest_canonical_sha256": manifest_canonical,
                    "receipt_bytes_sha256": _raw_sha(receipt_bytes),
                    "receipt_canonical_sha256": _canonical_sha(receipt),
                }
                marker_preimage = _commit_preimage(artifact, manifest, receipt, identity, date, selected_run, hashes)
                marker = {**marker_preimage, "commit_id": _canonical_sha(marker_preimage)}
                self._write(secure, paths["commit"], marker)
                self._fsync_run_dir(secure, date, selected_run)
                committed_chain = self._verify_run(secure, date, selected_run, identity)
                pointer = _current(artifact, identity, date, selected_run, hashes, committed_chain["commit_id"], committed_chain["commit_marker_bytes_sha256"], committed_chain["commit_marker_canonical_sha256"], committed_chain["commit_marker_size_bytes"])
                secure.replace_current_cas(paths["current"], expected_current_bytes_sha256=None, new_bytes=_canonical_bytes(pointer))
                verified = self._verify_current(secure, date, identity)
                return self._result(verified, idempotent=False)
        except (SecureEvidenceUnavailable, SecureEvidenceConflict) as error:
            raise StrictCommitError(str(error)) from error

    @staticmethod
    def _pool_membership(artifact: Mapping[str, Any]) -> dict[str, set[str]]:
        membership = {pool_id: set() for pool_id in REQUIRED_A_STAGE_POOL_IDS}
        sources = artifact.get("code_sources")
        if not isinstance(sources, Mapping):
            raise StrictCommitError("strict successor code source membership is missing")
        for code, pool_ids in sources.items():
            if not isinstance(pool_ids, list):
                raise StrictCommitError("strict successor code source membership is invalid")
            for pool_id in pool_ids:
                if pool_id not in membership:
                    raise StrictCommitError("strict successor code source pool is invalid")
                membership[pool_id].add(str(code))
        return membership

    @classmethod
    def _assert_successor_evolution(
        cls, previous: Mapping[str, Any], successor: Mapping[str, Any]
    ) -> None:
        """Enforce one explicit same-day append-only evolution policy."""

        previous_current = previous["current"]
        if successor.get("trade_date") != previous_current.get("trade_date"):
            raise StrictCommitError("strict successor trade_date mismatch")
        if successor.get("artifact_role") != STRICT_ROLE:
            raise StrictCommitError("strict successor role mismatch")
        for field in ("owner_id", "producer_id", "release_id", "lane_id"):
            if successor.get(field) != previous_current.get(field):
                raise StrictCommitError(f"strict successor {field} changed")

        previous_artifact = previous["artifact"]
        previous_codes = previous_artifact.get("codes")
        successor_codes = successor.get("codes")
        if not isinstance(previous_codes, list) or not isinstance(successor_codes, list):
            raise StrictCommitError("strict successor codes are invalid")
        # The aggregate is first-occurrence union in fixed physical pool order,
        # not a log: recovering an earlier pool can insert codes and can move an
        # overlapping old code to its newly authoritative earlier source.
        if (len(successor_codes) <= len(previous_codes)
                or len(set(successor_codes)) != len(successor_codes)
                or not set(previous_codes).issubset(successor_codes)):
            raise StrictCommitError(
                "strict successor must retain all prior candidates and add new codes"
            )

        previous_provenance = previous_artifact.get("source_pool_provenance")
        successor_provenance = successor.get("source_pool_provenance")
        if not isinstance(previous_provenance, list) or not isinstance(successor_provenance, list):
            raise StrictCommitError("strict successor source pool provenance is missing")
        if tuple(item.get("pool_id") for item in previous_provenance if isinstance(item, Mapping)) != REQUIRED_A_STAGE_POOL_IDS or tuple(item.get("pool_id") for item in successor_provenance if isinstance(item, Mapping)) != REQUIRED_A_STAGE_POOL_IDS:
            raise StrictCommitError("strict successor source pool set is incomplete")
        previous_by_pool = {item["pool_id"]: item for item in previous_provenance}
        successor_by_pool = {item["pool_id"]: item for item in successor_provenance}
        previous_membership = cls._pool_membership(previous_artifact)
        successor_membership = cls._pool_membership(successor)
        changed_pool_ids: list[str] = []
        raw_fields = (
            "pool_sha256",
            "artifact_raw_sha256",
            "manifest_raw_sha256",
            "receipt_raw_sha256",
        )
        static_fields = (
            "status",
            "producer_id",
            "source_role",
            "artifact_relative_path",
            "manifest_relative_path",
            "receipt_relative_path",
        )
        for pool_id in REQUIRED_A_STAGE_POOL_IDS:
            old = previous_by_pool[pool_id]
            new = successor_by_pool[pool_id]
            old_available = old.get("available", True) is True
            new_available = new.get("available", True) is True
            old_empty = old.get("valid_empty", False) is True
            new_empty = new.get("valid_empty", False) is True
            if not old_available:
                if not new_available:
                    # An unavailable lane may keep changing diagnostic text
                    # without changing the aggregate.  It remains a bound
                    # six-lane diagnostic slot until a verified source is
                    # actually available.
                    continue
                if new_empty or new.get("row_count", 0) <= 0:
                    raise StrictCommitError(
                        f"strict successor source pool {pool_id} did not recover rows"
                    )
                changed_pool_ids.append(pool_id)
                continue
            if not new_available:
                raise StrictCommitError(
                    f"strict successor source pool {pool_id} became unavailable"
                )
            if old_empty and not new_empty:
                # A previously verified empty diagnostic lane can recover into
                # a contributing lane.  The source-owned ordering checks below
                # permit only physical first-source promotion, never arbitrary
                # reordering of the retained contribution from an existing lane.
                changed_pool_ids.append(pool_id)
                continue
            if any(new.get(field) != old.get(field) for field in static_fields):
                raise StrictCommitError(f"strict successor source pool {pool_id} identity changed")
            if all(new.get(field) == old.get(field) for field in raw_fields):
                continue
            # ``preselection_pools/<date>/manifest.json`` is one shared
            # physical file.  An allowed append to one pool therefore changes
            # its raw SHA for every pool even when the per-pool artifact and
            # receipt bytes did not change.  Treat that collateral manifest
            # rewrite as unchanged source evidence; the fresh physical read
            # above still verifies the complete shared manifest.
            if (
                new.get("manifest_raw_sha256") != old.get("manifest_raw_sha256")
                and all(
                    new.get(field) == old.get(field)
                    for field in raw_fields
                    if field != "manifest_raw_sha256"
                )
            ):
                continue
            changed_pool_ids.append(pool_id)
            if pool_id not in _APPEND_ONLY_POOL_IDS:
                raise StrictCommitError(
                    f"strict successor source pool {pool_id} raw evidence changed outside append-only policy"
                )
            old_count = old.get("row_count")
            new_count = new.get("row_count")
            if not isinstance(old_count, int) or not isinstance(new_count, int) or new_count <= old_count:
                raise StrictCommitError(
                    f"strict successor source pool {pool_id} did not append rows"
                )
            if not previous_membership[pool_id].issubset(successor_membership[pool_id]):
                raise StrictCommitError(
                    f"strict successor source pool {pool_id} removed prior membership"
                )
        if not changed_pool_ids:
            raise StrictCommitError("strict successor has no append-only source evidence change")

        successor_sources = successor.get("code_sources")
        if not isinstance(successor_sources, Mapping):
            raise StrictCommitError("strict successor code sources are missing")
        for code in previous_codes:
            old_sources = previous_artifact["code_sources"].get(code)
            new_sources = successor_sources.get(code)
            if not isinstance(old_sources, list) or not isinstance(new_sources, list):
                raise StrictCommitError(f"strict successor lost prior code source {code}")
            if any(pool_id not in new_sources for pool_id in old_sources):
                raise StrictCommitError(f"strict successor changed source membership for {code}")

        # publish_successor already binds this artifact to a fresh physical
        # snapshot, and rechecks that snapshot under the data-root lock.  Here
        # bind the *evolution* to the immutable predecessor's source ownership.
        # A set-only or aggregate-subsequence test is insufficient: the former
        # accepts malicious reorders; the latter rejects legitimate overlaps.
        positions = {pool_id: index for index, pool_id in enumerate(REQUIRED_A_STAGE_POOL_IDS)}
        old_sources_by_code = previous_artifact["code_sources"]
        origin_positions = [positions[successor_sources[code][0]] for code in successor_codes]
        if origin_positions != sorted(origin_positions):
            raise StrictCommitError("strict successor violates physical pool order")
        for code in previous_codes:
            old_origin = old_sources_by_code[code][0]
            new_origin = successor_sources[code][0]
            if old_origin != new_origin and (
                positions[new_origin] >= positions[old_origin]
                or new_origin not in changed_pool_ids
                or new_origin in old_sources_by_code[code]
            ):
                raise StrictCommitError(f"strict successor unexplained source promotion for {code}")
        for pool_id in REQUIRED_A_STAGE_POOL_IDS:
            retained = [code for code in previous_codes
                        if old_sources_by_code[code][0] == pool_id
                        and successor_sources[code][0] == pool_id]
            contributed = [code for code in successor_codes
                           if successor_sources[code][0] == pool_id]
            # Keep each prior first-source contribution as a prefix.  New or
            # promoted members may follow it; a newly recovered lane has no
            # prior prefix and follows its strictly verified physical row order.
            if contributed[:len(retained)] != retained:
                raise StrictCommitError(
                    f"strict successor reordered prior source contribution: {pool_id}"
                )

    @staticmethod
    def _successor_result(
        chain: Mapping[str, Any], receipt: Mapping[str, Any], receipt_path: Path, *, idempotent: bool
    ) -> dict[str, Any]:
        result = StageAcquisitionUniverseCommit._result(chain, idempotent=idempotent)
        result.update(
            {
                "status": "SUPERSEDED",
                "current_status": chain["current"]["status"],
                "supersession_receipt_path": receipt_path,
                "supersession_receipt": dict(receipt),
                "predecessor": receipt.get("predecessor"),
            }
        )
        return result

    def publish_successor(
        self,
        payload: Mapping[str, Any],
        *,
        expected_current_sha256: str,
        reason: str,
        run_id: str | None = None,
        identity: EvidenceIdentity | None = None,
    ) -> dict[str, Any]:
        """Publish a same-day strict successor using only raw current CAS."""

        if not isinstance(identity, EvidenceIdentity):
            raise StrictCommitError("strict successor publication requires evidence identity")
        identity.validate()
        _reject_unsafe_strict_fields(payload)
        expected = _require_sha(
            expected_current_sha256,
            "strict successor expected current raw SHA",
        ).lower()
        reason_text = _require_nonempty_text(reason, "strict successor reason")
        date = _safe_date(payload.get("trade_date") if isinstance(payload, Mapping) else None)
        try:
            snapshot = read_strict_a_preselection_snapshot(self.root, date)
            _validate_physical_input(payload, snapshot)
            artifact = _normalize_strict_artifact(payload, snapshot, identity)
        except (StageAcquisitionContractError, OSError, ValueError) as error:
            raise StrictCommitError(
                f"required A pool strict physical snapshot cannot be confirmed: {error}"
            ) from error
        _validate_artifact(artifact, date, identity)
        artifact_bytes = _canonical_bytes(artifact)
        artifact_canonical = _canonical_sha(artifact)
        selected_run = _safe_run(
            run_id or f"{date}-{STRICT_ROLE.lower()}-{artifact_canonical[:12]}"
        )
        paths = _paths(date, selected_run)
        manifest = _manifest(
            artifact,
            identity,
            date,
            selected_run,
            _raw_sha(artifact_bytes),
            artifact_canonical,
            len(artifact_bytes),
        )
        manifest_bytes = _canonical_bytes(manifest)
        manifest_canonical = _canonical_sha(manifest)
        receipt = _receipt(
            artifact,
            manifest,
            identity,
            date,
            selected_run,
            _raw_sha(artifact_bytes),
            artifact_canonical,
            _raw_sha(manifest_bytes),
            manifest_canonical,
            len(manifest_bytes),
        )
        supersession_relative = self._supersession_relative(
            date, expected, artifact_canonical
        )
        lock = owned_interprocess_lock(
            self.root / ".import.lock",
            timeout_seconds=10,
            timeout_message="data-root import lock timeout",
        )
        try:
            with lock, self._secure() as secure:
                _revalidate_physical_snapshot(self.root, date, snapshot)
                try:
                    current = self._verify_current(secure, date, identity)
                except StrictCommitError as error:
                    raise StrictCommitError(
                        f"strict successor current cannot be confirmed: {error}"
                    ) from error
                current_sha = current["current_bytes_sha256"]
                if expected == current["artifact_bytes_sha256"]:
                    raise StrictCommitError(
                        "strict successor artifact SHA is not a current CAS token"
                    )

                existing_receipt: dict[str, Any] | None = None
                try:
                    existing_result = secure.read_regular_bytes(supersession_relative)
                except SecureEvidenceUnavailable:
                    existing_result = None
                if existing_result is not None:
                    existing_receipt = _decode(
                        existing_result, "strict supersession receipt"
                    )
                    if current["run_id"] == existing_receipt.get("successor_run_id"):
                        # The current verifier has already checked the receipt
                        # against this successor.  Compare the request fields
                        # here so a changed reason or artifact cannot be
                        # mistaken for an idempotent retry.
                        if (
                            existing_receipt.get("reason") != reason_text
                            or existing_receipt.get("expected_current_bytes_sha256") != expected
                            or existing_receipt.get("successor", {}).get("artifact_canonical_sha256") != artifact_canonical
                        ):
                            raise StrictCommitError(
                                "strict supersession receipt request conflict"
                            )
                        return self._successor_result(
                            current,
                            existing_receipt,
                            self.root / supersession_relative,
                            idempotent=True,
                        )
                    if current_sha == expected:
                        _successor_chain, successor_pointer = self._verify_supersession_for_predecessor(
                            secure,
                            date,
                            identity,
                            existing_receipt,
                            supersession_relative,
                            current,
                            expected,
                            reason_text,
                            artifact_canonical,
                        )
                        successor_bytes = _canonical_bytes(successor_pointer)
                        secure.replace_current_cas(
                            paths["current"],
                            expected_current_bytes_sha256=expected,
                            new_bytes=successor_bytes,
                        )
                        verified = self._verify_current(secure, date, identity)
                        return self._successor_result(
                            verified,
                            existing_receipt,
                            self.root / supersession_relative,
                            idempotent=True,
                        )
                    raise StrictCommitError(
                        "strict successor current raw SHA mismatch"
                    )
                if expected != current_sha:
                    suffix = " (artifact SHA is not a current CAS token)" if expected == current["artifact_bytes_sha256"] else ""
                    raise StrictCommitError(
                        f"strict successor current raw SHA mismatch{suffix}"
                    )

                recovered = self._recover_committed_successor_orphan(
                    secure,
                    date,
                    identity,
                    current,
                    current_sha,
                    expected,
                    artifact_canonical,
                    reason_text,
                    selected_run,
                    supersession_relative,
                )
                if recovered is not None:
                    return recovered

                # A fully equal strict artifact is an ordinary idempotent
                # retry.  It is not a successor and does not create lineage.
                if current["artifact_canonical_sha256"] == artifact_canonical:
                    return self._result(current, idempotent=True)
                if selected_run == current["run_id"]:
                    raise StrictCommitError("strict successor run_id equals current run")

                predecessor = self._predecessor_summary(current, current_sha)
                self._assert_successor_evolution(current, artifact)
                marker_supersession = {
                    "relative": supersession_relative,
                    "expected_current_bytes_sha256": expected,
                    "successor_artifact_canonical_sha256": artifact_canonical,
                    "successor_run_id": selected_run,
                    "reason": reason_text,
                    "evolution": STRICT_SUCCESSOR_EVOLUTION,
                    "target_current_relative": paths["current"],
                    "successor_current_relative": paths["current"],
                }
                marker_preimage = _commit_preimage(
                    artifact,
                    manifest,
                    receipt,
                    identity,
                    date,
                    selected_run,
                    {
                        "artifact_bytes_sha256": _raw_sha(artifact_bytes),
                        "artifact_canonical_sha256": artifact_canonical,
                        "manifest_bytes_sha256": _raw_sha(manifest_bytes),
                        "manifest_canonical_sha256": manifest_canonical,
                        "receipt_bytes_sha256": _raw_sha(_canonical_bytes(receipt)),
                        "receipt_canonical_sha256": _canonical_sha(receipt),
                    },
                    predecessor=predecessor,
                    supersession=marker_supersession,
                )
                marker = {**marker_preimage, "commit_id": _canonical_sha(marker_preimage)}

                self._write(secure, paths["artifact"], artifact)
                self._write(secure, paths["manifest"], manifest)
                self._write(secure, paths["receipt"], receipt)
                hashes = {
                    "artifact_bytes_sha256": _raw_sha(artifact_bytes),
                    "artifact_canonical_sha256": artifact_canonical,
                    "manifest_bytes_sha256": _raw_sha(manifest_bytes),
                    "manifest_canonical_sha256": manifest_canonical,
                    "receipt_bytes_sha256": _raw_sha(_canonical_bytes(receipt)),
                    "receipt_canonical_sha256": _canonical_sha(receipt),
                }
                self._write(secure, paths["commit"], marker)
                self._fsync_run_dir(secure, date, selected_run)
                successor_chain = self._verify_run(secure, date, selected_run, identity)
                pointer = _current(
                    artifact,
                    identity,
                    date,
                    selected_run,
                    hashes,
                    successor_chain["commit_id"],
                    successor_chain["commit_marker_bytes_sha256"],
                    successor_chain["commit_marker_canonical_sha256"],
                    successor_chain["commit_marker_size_bytes"],
                    predecessor=predecessor,
                )
                pointer_bytes = _canonical_bytes(pointer)
                supersession = self._build_supersession_receipt(
                    date=date,
                    identity=identity,
                    reason=reason_text,
                    expected_current_sha256=expected,
                    predecessor=predecessor,
                    previous_current=current["current"],
                    successor_chain=successor_chain,
                    successor_current=pointer,
                    target_current_relative=paths["current"],
                )
                self._write(secure, supersession_relative, supersession)
                receipt_result = secure.read_regular_bytes(supersession_relative)
                receipt_check = _decode(receipt_result, "strict supersession receipt")
                if receipt_check != supersession:
                    raise StrictCommitError("strict supersession receipt verification failed")
                secure.replace_current_cas(
                    paths["current"],
                    expected_current_bytes_sha256=current_sha,
                    new_bytes=pointer_bytes,
                )
                verified = self._verify_current(secure, date, identity)
                return self._successor_result(
                    verified, supersession, self.root / supersession_relative, idempotent=False
                )
        except (SecureEvidenceUnavailable, SecureEvidenceConflict) as error:
            raise StrictCommitError(str(error)) from error

    def read_current(self, trade_date: str, *, identity: EvidenceIdentity | None = None) -> dict[str, Any]:
        date = _safe_date(trade_date)
        try:
            with self._secure() as secure:
                if identity is None:
                    try:
                        current_bytes = secure.read_regular_bytes(_paths(date, "placeholder")["current"])
                        current_payload = _decode(current_bytes, "strict current")
                        identity = EvidenceIdentity.from_mapping(current_payload)
                    except (SecureEvidenceUnavailable, SecureEvidenceConflict) as error:
                        raise StrictCommitError("strict current is missing or unavailable") from error
                if not isinstance(identity, EvidenceIdentity):
                    raise StrictCommitError("strict read requires EvidenceIdentity")
                identity.validate()
                return self._verify_current(secure, date, identity)
        except (SecureEvidenceUnavailable, SecureEvidenceConflict) as error:
            raise StrictCommitError("strict current is missing or unavailable") from error


class StrictStageAcquisitionUniverseFacade:
    """Thin store mixin for strict publication and verification."""

    def publish(self, payload: Mapping[str, Any], *, run_id: str | None = None, identity: EvidenceIdentity | None = None) -> dict[str, Any]:
        if identity is None:
            raise StrictCommitError("strict publication requires evidence identity")
        return StageAcquisitionUniverseCommit(self.root).publish(payload, run_id=run_id, identity=identity)

    def publish_successor(
        self,
        payload: Mapping[str, Any],
        *,
        expected_current_sha256: str,
        reason: str,
        run_id: str | None = None,
        identity: EvidenceIdentity | None = None,
    ) -> dict[str, Any]:
        if identity is None:
            raise StrictCommitError("strict successor publication requires evidence identity")
        return StageAcquisitionUniverseCommit(self.root).publish_successor(
            payload,
            expected_current_sha256=expected_current_sha256,
            reason=reason,
            run_id=run_id,
            identity=identity,
        )

    def read_strict_verified(self, trade_date: str, *, identity: EvidenceIdentity | None = None) -> dict[str, Any]:
        return StageAcquisitionUniverseCommit(self.root).read_current(trade_date, identity=identity)


StrictStageAcquisitionCommit = StageAcquisitionUniverseCommit


def publish_strict(root: Path | str, payload: Mapping[str, Any], *, run_id: str | None = None, identity: EvidenceIdentity | None = None) -> dict[str, Any]:
    return StageAcquisitionUniverseCommit(root).publish(payload, run_id=run_id, identity=identity)


__all__ = [
    "COMMIT_STATUS",
    "DIGEST_MODE",
    "EvidenceIdentity",
    "STRICT_ARTIFACT_SCHEMA",
    "STRICT_ARTIFACT_VERSION",
    "STRICT_COMMIT_SCHEMA",
    "STRICT_CURRENT_SCHEMA",
    "STRICT_MANIFEST_SCHEMA",
    "STRICT_RECEIPT_SCHEMA",
    "STRICT_ROLE",
    "STRICT_SUCCESSOR_EVOLUTION",
    "STRICT_SUPERSESSION_SCHEMA",
    "StrictCommitError",
    "StageAcquisitionUniverseCommit",
    "StrictStageAcquisitionUniverseFacade",
    "StrictStageAcquisitionCommit",
    "publish_strict",
]
