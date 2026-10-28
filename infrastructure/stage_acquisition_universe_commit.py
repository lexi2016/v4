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
    from infrastructure._stage_acquisition_universe_commit_parts.artifact_validation import __reject_unsafe_strict_fields_body as _v4_impl
    return _v4_impl(globals(), value, path)


class StrictCommitError(ValueError):
    """A strict chain is absent, malformed, conflicting, or not promotable."""


@dataclass(frozen=True, slots=True)
class EvidenceIdentity:
    owner_id: str
    producer_id: str
    release_id: str
    lane_id: str

    def validate(self) -> None:
        from infrastructure._stage_acquisition_universe_commit_parts.identity_primitives import _EvidenceIdentity_validate_body as _v4_impl
        return _v4_impl(globals(), self)

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
    from infrastructure._stage_acquisition_universe_commit_parts.identity_primitives import __validate_lineage_predecessor_body as _v4_impl
    return _v4_impl(globals(), predecessor, trade_date, identity)


def _validate_marker_supersession(
    supersession: Mapping[str, Any], trade_date: str, identity: EvidenceIdentity
) -> None:
    from infrastructure._stage_acquisition_universe_commit_parts.identity_primitives import __validate_marker_supersession_body as _v4_impl
    return _v4_impl(globals(), supersession, trade_date, identity)


_POOL_BINDING_FIELDS = (
    "pool_id",
    "status",
    "producer_id",
    "source_role",
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
    from infrastructure._stage_acquisition_universe_commit_parts.artifact_validation import __validate_physical_input_body as _v4_impl
    return _v4_impl(globals(), payload, snapshot)


def _normalize_strict_artifact(
    payload: Mapping[str, Any],
    snapshot: StrictAPreselectionSnapshot,
    identity: EvidenceIdentity,
) -> dict[str, Any]:
    """Copy a verified Gate2 artifact into the strict V3 wire schema."""
    from infrastructure._stage_acquisition_universe_commit_parts.artifact_validation import __normalize_strict_artifact_body as _v4_impl
    return _v4_impl(globals(), payload, snapshot, identity)


def _pool_value(item: Mapping[str, Any], primary: str, alias: str, label: str) -> str:
    value = item.get(primary, item.get(alias))
    return _require_sha(value, label)


def _validate_artifact(payload: Mapping[str, Any], trade_date: str, identity: EvidenceIdentity) -> None:
    from infrastructure._stage_acquisition_universe_commit_parts.artifact_validation import __validate_artifact_body as _v4_impl
    return _v4_impl(globals(), payload, trade_date, identity)


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
    from infrastructure._stage_acquisition_universe_commit_parts.commit_metadata import __manifest_body as _v4_impl
    return _v4_impl(globals(), artifact, identity, date, run, artifact_raw, artifact_canonical, artifact_size)


def _receipt(artifact: Mapping[str, Any], manifest: Mapping[str, Any], identity: EvidenceIdentity, date: str, run: str, artifact_raw: str, artifact_canonical: str, manifest_raw: str, manifest_canonical: str, manifest_size: int) -> dict[str, Any]:
    from infrastructure._stage_acquisition_universe_commit_parts.commit_metadata import __receipt_body as _v4_impl
    return _v4_impl(globals(), artifact, manifest, identity, date, run, artifact_raw, artifact_canonical, manifest_raw, manifest_canonical, manifest_size)


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
    from infrastructure._stage_acquisition_universe_commit_parts.commit_metadata import __commit_preimage_body as _v4_impl
    return _v4_impl(globals(), artifact, manifest, receipt, identity, date, run, hashes, predecessor=predecessor, supersession=supersession)


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
    from infrastructure._stage_acquisition_universe_commit_parts.commit_metadata import __current_body as _v4_impl
    return _v4_impl(globals(), artifact, identity, date, run, hashes, commit_id, marker_raw, marker_canonical, marker_size, predecessor=predecessor)


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
    root: Path,
    trade_date: str,
    expected: StrictAPreselectionSnapshot,
    *,
    lock_lease: object,
) -> None:
    """Refuse publication if physical pool evidence changed before the lock.

    The first snapshot is needed to build the caller's proposal.  A fresh
    snapshot inside the import lock is the publication gate: pool writers use
    that same lock, so the verified source cannot change between this check and
    the commit writes.
    """
    from infrastructure._stage_acquisition_universe_commit_parts.artifact_validation import __revalidate_physical_snapshot_body as _v4_impl
    return _v4_impl(globals(), root, trade_date, expected, lock_lease=lock_lease)


class StageAcquisitionUniverseCommit:
    """Writer and verifier for one strict exact-date candidate release."""

    def __init__(self, root: Path | str, *, max_file_bytes: int = _MAX_BYTES,
                 preselection_source_root: Path | str | None = None) -> None:
        self.root = Path(root)
        self.max_file_bytes = max_file_bytes
        from infrastructure.stage_source_roots import resolve_source_root
        self.preselection_source_root = resolve_source_root(self.root, preselection_source_root)
        self._explicit_source_root = self.preselection_source_root.absolute() != self.root.absolute()

    def _publication_locks(self):
        from infrastructure.stage_source_roots import publication_source_lease
        return publication_source_lease(self.root, self.preselection_source_root)

    def _bind_source_root(self, artifact: dict[str, Any]) -> None:
        observed = artifact.get("preselection_source_root")
        expected = str(self.preselection_source_root)
        if observed is not None and observed != expected:
            raise StrictCommitError("preselection source root binding mismatch")
        if self._explicit_source_root:
            artifact["preselection_source_root"] = expected

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
        from infrastructure._stage_acquisition_universe_commit_parts.current_verification import _StageAcquisitionUniverseCommit__verify_run_body as _v4_impl
        return _v4_impl(globals(), self, secure, date, run, identity)

    def _verify_current(self, secure: SecureEvidenceRoot, date: str, identity: EvidenceIdentity, expected: str | None = None) -> dict[str, Any]:
        from infrastructure._stage_acquisition_universe_commit_parts.current_verification import _StageAcquisitionUniverseCommit__verify_current_body as _v4_impl
        return _v4_impl(globals(), self, secure, date, identity, expected)

    @staticmethod
    def _supersession_relative(
        date: str, expected_current_sha256: str, successor_artifact_canonical_sha256: str
    ) -> str:
        from infrastructure._stage_acquisition_universe_commit_parts.identity_primitives import _StageAcquisitionUniverseCommit__supersession_relative_body as _v4_impl
        return _v4_impl(globals(), date, expected_current_sha256, successor_artifact_canonical_sha256)

    @staticmethod
    def _predecessor_summary(
        chain: Mapping[str, Any], current_sha256: str
    ) -> dict[str, Any]:
        from infrastructure._stage_acquisition_universe_commit_parts.supersession_receipts import _StageAcquisitionUniverseCommit__predecessor_summary_body as _v4_impl
        return _v4_impl(globals(), chain, current_sha256)

    @staticmethod
    def _successor_lineage(chain: Mapping[str, Any]) -> dict[str, Any]:
        from infrastructure._stage_acquisition_universe_commit_parts.supersession_receipts import _StageAcquisitionUniverseCommit__successor_lineage_body as _v4_impl
        return _v4_impl(globals(), chain)

    @staticmethod
    def _chain_hashes(chain: Mapping[str, Any]) -> dict[str, str]:
        from infrastructure._stage_acquisition_universe_commit_parts.identity_primitives import _StageAcquisitionUniverseCommit__chain_hashes_body as _v4_impl
        return _v4_impl(globals(), chain)

    @staticmethod
    def _current_from_chain(
        chain: Mapping[str, Any],
        identity: EvidenceIdentity,
        date: str,
        *,
        predecessor: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Rebuild a current pointer solely from its committed run chain."""
        from infrastructure._stage_acquisition_universe_commit_parts.supersession_receipts import _StageAcquisitionUniverseCommit__current_from_chain_body as _v4_impl
        return _v4_impl(globals(), chain, identity, date, predecessor=predecessor)

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
        from infrastructure._stage_acquisition_universe_commit_parts.supersession_receipts import _StageAcquisitionUniverseCommit__build_supersession_receipt_body as _v4_impl
        return _v4_impl(globals(), self, date=date, identity=identity, reason=reason, expected_current_sha256=expected_current_sha256, predecessor=predecessor, previous_current=previous_current, successor_chain=successor_chain, successor_current=successor_current, target_current_relative=target_current_relative)

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
        from infrastructure._stage_acquisition_universe_commit_parts.supersession_verification import _StageAcquisitionUniverseCommit__verify_supersession_for_current_body as _v4_impl
        return _v4_impl(globals(), self, secure, date, identity, chain, current, current_sha256, predecessor, marker_supersession)

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
        from infrastructure._stage_acquisition_universe_commit_parts.supersession_verification import _StageAcquisitionUniverseCommit__verify_supersession_for_predecessor_body as _v4_impl
        return _v4_impl(globals(), self, secure, date, identity, receipt, receipt_relative, predecessor_chain, expected_current_sha256, reason, requested_artifact_canonical_sha256)


    def _run_root(self, date: str) -> Path:
        return self.root / f"runs/{date}/{STRICT_ROLE}"

    def _scan_orphans(self, secure: SecureEvidenceRoot, date: str, identity: EvidenceIdentity, selected_run: str) -> tuple[list[dict[str, Any]], bool]:
        from infrastructure._stage_acquisition_universe_commit_parts.orphan_recovery import _StageAcquisitionUniverseCommit__scan_orphans_body as _v4_impl
        return _v4_impl(globals(), self, secure, date, identity, selected_run)

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
        from infrastructure._stage_acquisition_universe_commit_parts.orphan_recovery import _StageAcquisitionUniverseCommit__recover_committed_successor_orphan_body as _v4_impl
        return _v4_impl(globals(), self, secure, date, identity, current, current_sha256, expected_current_sha256, artifact_canonical_sha256, reason, selected_run, supersession_relative)

    @staticmethod
    def _result(chain: Mapping[str, Any], *, idempotent: bool) -> dict[str, Any]:
        from infrastructure._stage_acquisition_universe_commit_parts.identity_primitives import _StageAcquisitionUniverseCommit__result_body as _v4_impl
        return _v4_impl(globals(), chain, idempotent=idempotent)

    def publish(
        self,
        payload: Mapping[str, Any],
        *,
        run_id: str | None = None,
        identity: EvidenceIdentity | None = None,
    ) -> dict[str, Any]:
        from infrastructure._stage_acquisition_universe_commit_parts.initial_publication import _StageAcquisitionUniverseCommit_publish_body as _v4_impl
        return _v4_impl(globals(), self, payload, run_id=run_id, identity=identity)

    @staticmethod
    def _pool_membership(artifact: Mapping[str, Any]) -> dict[str, set[str]]:
        from infrastructure._stage_acquisition_universe_commit_parts.identity_primitives import _StageAcquisitionUniverseCommit__pool_membership_body as _v4_impl
        return _v4_impl(globals(), artifact)

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
        if len(successor_codes) <= len(previous_codes) or successor_codes[: len(previous_codes)] != previous_codes:
            raise StrictCommitError(
                "strict successor must retain the prior candidate order and append new codes"
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
                # a contributing lane.  The aggregate prefix check above still
                # prevents a newly recovered lane from silently reordering
                # existing candidates.
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

    @staticmethod
    def _successor_result(
        chain: Mapping[str, Any], receipt: Mapping[str, Any], receipt_path: Path, *, idempotent: bool
    ) -> dict[str, Any]:
        from infrastructure._stage_acquisition_universe_commit_parts.identity_primitives import _StageAcquisitionUniverseCommit__successor_result_body as _v4_impl
        return _v4_impl(globals(), chain, receipt, receipt_path, idempotent=idempotent)

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
        from infrastructure._stage_acquisition_universe_commit_parts.successor_publication import _StageAcquisitionUniverseCommit_publish_successor_body as _v4_impl
        return _v4_impl(globals(), self, payload, expected_current_sha256=expected_current_sha256, reason=reason, run_id=run_id, identity=identity)

    def read_current(self, trade_date: str, *, identity: EvidenceIdentity | None = None) -> dict[str, Any]:
        from infrastructure._stage_acquisition_universe_commit_parts.identity_primitives import _StageAcquisitionUniverseCommit_read_current_body as _v4_impl
        return _v4_impl(globals(), self, trade_date, identity=identity)


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
        from infrastructure._stage_acquisition_universe_commit_parts.successor_publication import _StrictStageAcquisitionUniverseFacade_publish_successor_body as _v4_impl
        return _v4_impl(globals(), self, payload, expected_current_sha256=expected_current_sha256, reason=reason, run_id=run_id, identity=identity)

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
