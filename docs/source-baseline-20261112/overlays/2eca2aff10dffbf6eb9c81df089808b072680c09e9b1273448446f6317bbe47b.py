"""Immutable exact-date A-share stage-acquisition universe evidence.

The producer is intentionally a small boundary around the already-authoritative
``domains.preselection.preselection`` projection.  It stores canonical symbols,
not copies of physical pool rows, so auxiliary review lanes cannot silently
become stage candidates.
"""
from __future__ import annotations

import re
import json
import hashlib
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from infrastructure.data_store import NativeDataStore, _canonical_bytes, _date, _sha256
from infrastructure.stage_acquisition_universe_commit import (
    EvidenceIdentity,
    StrictCommitError,
    StrictStageAcquisitionUniverseFacade,
)


ARTIFACT_ROLE = "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V2"
SCHEMA_VERSION = ARTIFACT_ROLE
ARTIFACT_VERSION = "V2"
MANIFEST_SCHEMA = "v3_5.stage_acquisition_universe.manifest.v2"
RECEIPT_SCHEMA = "v3_5.stage_acquisition_universe.receipt.v2"
CURRENT_SCHEMA = "v3_5.stage_acquisition_universe.current.v2"
COMMIT_SCHEMA = "v3_5.stage_acquisition_universe.commit.v1"
COMMIT_MARKER_SCHEMA = COMMIT_SCHEMA
COMMIT_STATUS = "COMMITTED"
SUPERSESSION_SCHEMA = "v3_5.stage_acquisition_universe.supersession.v1"
_CODE_RE = re.compile(r"^A\.\d{6}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_RUN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")
_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
_COMMIT_POINTER_FIELDS = (
    "commit_id",
    "commit_marker_relative",
    "commit_marker_sha256",
    "predecessor",
)


def _safe_run_id(value: Any) -> str:
    if not isinstance(value, str) or not _RUN_RE.fullmatch(value):
        raise ValueError("run_id must be a safe slug")
    return value


def _digest(value: Any) -> str:
    return _sha256(value)


def _assert_safe_tree(value: Any) -> None:
    """Reject accidental promotion/order semantics anywhere in the artifact."""

    if isinstance(value, Mapping):
        for key, nested in value.items():
            folded = str(key).casefold()
            if folded in {"buy", "sell", "order", "trade", "side", "action", "signal"}:
                if nested not in (False, 0, None, "", "WATCH_ONLY"):
                    raise ValueError("unsafe stage-acquisition action")
            if folded in {"production_allowed", "buy_gate_updated", "orders_sent", "order_sent"}:
                if nested not in (False, 0, None, ""):
                    raise ValueError("unsafe stage-acquisition trading state")
            _assert_safe_tree(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_safe_tree(nested)


def _canonical_code(row: Mapping[str, Any], index: int) -> str:
    """Return one canonical A-share symbol without changing source order."""

    market = str(row.get("market") or "").strip().upper()
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
    if text.endswith(".SH") or text.endswith(".SZ") or text.endswith(".BJ"):
        text = text[:-3]
    if re.fullmatch(r"\d{6}", text):
        text = f"A.{text}"
    if not _CODE_RE.fullmatch(text):
        raise ValueError(f"a_all_pool_rows[{index}] is not a canonical A code")
    if market and market not in {"A", "A_SHARE", "ASHARE", "A股"}:
        raise ValueError(f"a_all_pool_rows[{index}] market is not A")
    return text


def _pool_provenance(projection: Mapping[str, Any]) -> list[dict[str, Any]]:
    pools = projection.get("pools")
    if pools is None:
        return []
    if not isinstance(pools, list):
        raise ValueError("preselection projection pools must be a list")
    provenance: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, pool in enumerate(pools):
        if not isinstance(pool, Mapping):
            raise ValueError(f"preselection projection pool {index} is invalid")
        pool_id = str(pool.get("pool_id") or "").strip()
        if not pool_id or pool_id in seen:
            raise ValueError("preselection projection pool identity is invalid")
        rows = pool.get("rows", [])
        if not isinstance(rows, list):
            raise ValueError(f"preselection projection pool {pool_id} rows are invalid")
        seen.add(pool_id)
        pool_sha = _digest(pool)
        provenance.append(
            {
                "pool_id": pool_id,
                "status": str(pool.get("status") or ""),
                "row_count": len(rows),
                "pool_sha256": pool_sha,
            }
        )
    return provenance


def build_stage_acquisition_universe(
    projection: Mapping[str, Any],
    trade_date: str | None = None,
) -> dict[str, Any]:
    """Build the V2 artifact from one complete preselection projection.

    The source is a strict projection of all six exact-date physical A pools.
    Presentation-only projections with synthetic missing lanes are rejected;
    no HTTP endpoint, V3 module, or source-lane fallback is inspected.
    """

    # The strict physical reader returns a frozen snapshot that already owns
    # the exact artifact/manifest/receipt bytes.  Keep the legacy mapping
    # builder below for import compatibility, but never route a snapshot back
    # through the display projection where raw provenance would be lost.
    from infrastructure.stage_acquisition_universe_contracts import (
        StrictAPreselectionSnapshot,
        build_strict_stage_acquisition_universe,
    )

    if isinstance(projection, StrictAPreselectionSnapshot):
        if trade_date is not None and projection.trade_date != _date(str(trade_date)):
            raise ValueError("preselection projection trade_date mismatch")
        return build_strict_stage_acquisition_universe(projection)
    if not isinstance(projection, Mapping):
        raise ValueError("preselection projection must be an object")
    source_date = _date(str(projection.get("trade_date") or ""))
    requested_date = source_date if trade_date is None else _date(str(trade_date))
    if source_date != requested_date:
        raise ValueError("preselection projection trade_date mismatch")

    # The presentation projection can contain explicit EXPECTED_MISSING lanes
    # and is therefore not sufficient as stage membership authority.  Validate
    # the six physical A pools before touching any artifact/store state.  The
    # import is local to preserve the historical import boundary: the strict
    # reader itself depends on PreselectionPoolStore.
    from domains.stage_preselection_projection import validate_complete_a_pool_set

    validated_projection = validate_complete_a_pool_set(projection, requested_date)
    projection = validated_projection["projection"]
    rows = validated_projection["a_all_pool_rows"]
    reported_count = validated_projection["a_all_pool_row_count"]

    codes: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"a_all_pool_rows[{index}] is invalid")
        code = _canonical_code(row, index)
        if code in seen:
            raise ValueError(f"duplicate canonical A code: {code}")
        seen.add(code)
        codes.append(code)

    projection_digest = _digest(projection)
    provenance = _pool_provenance(projection)
    source_status = str(projection.get("data_status") or projection.get("status") or "")
    cannot_confirm = [str(item) for item in projection.get("cannot_confirm", []) or [] if str(item)]
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "artifact_role": ARTIFACT_ROLE,
        "artifact_version": ARTIFACT_VERSION,
        "authority": "LEGACY_NON_AUTHORITATIVE_PROJECTION",
        "status": "READY",
        "trade_date": source_date,
        "codes": codes,
        "row_count": len(codes),
        "codes_sha256": _digest(codes),
        "source_projection_sha256": projection_digest,
        "source_projection_row_count": reported_count,
        "source_projection_status": source_status,
        "source_pool_provenance": provenance,
        "source_pool_provenance_sha256": _digest(provenance),
        "source_merge_role": "STAGE_ACQUISITION_INPUT",
        "stage_selection_eligible": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "cannot_confirm": cannot_confirm,
    }
    # Keep this historical builder import-compatible for display/replay
    # callers.  Its explicit legacy authority marker is intentionally not
    # accepted by ``validate_stage_acquisition_universe`` or either publish
    # method, so it cannot create or advance the authoritative current pointer.
    return artifact


def validate_stage_acquisition_universe(payload: Mapping[str, Any]) -> str:
    """Validate artifact identity, lineage, ordered codes, and safety flags."""

    if not isinstance(payload, Mapping):
        raise ValueError("stage-acquisition artifact must be an object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid stage-acquisition universe schema")
    if (
        payload.get("artifact_role") != ARTIFACT_ROLE
        or payload.get("artifact_version") != ARTIFACT_VERSION
    ):
        raise ValueError("invalid stage-acquisition universe identity")
    from infrastructure.stage_acquisition_universe_contracts import (
        StageAcquisitionContractError,
        validate_strict_stage_acquisition_artifact,
    )

    trade_date = _date(str(payload.get("trade_date") or ""))
    if payload.get("status") != "READY":
        raise ValueError("stage-acquisition universe must be READY")
    codes = payload.get("codes")
    if not isinstance(codes, list) or not codes:
        raise ValueError("stage-acquisition universe codes are missing")
    seen: set[str] = set()
    for code in codes:
        if not isinstance(code, str) or not _CODE_RE.fullmatch(code) or code in seen:
            raise ValueError("invalid or duplicate canonical A code")
        seen.add(code)
    row_count = payload.get("row_count")
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count != len(codes):
        raise ValueError("stage-acquisition universe row_count mismatch")
    for name in ("codes_sha256", "source_projection_sha256"):
        value = payload.get(name)
        if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
            raise ValueError(f"invalid {name}")
    if payload["codes_sha256"] != _digest(codes):
        raise ValueError("stage-acquisition codes SHA mismatch")
    if payload.get("source_projection_row_count") != row_count:
        raise ValueError("stage-acquisition source projection row_count mismatch")
    try:
        if validate_strict_stage_acquisition_artifact(payload) != trade_date:
            raise ValueError("stage-acquisition artifact identity mismatch")
    except StageAcquisitionContractError as error:
        raise ValueError(str(error)) from error
    fixed = {
        "source_merge_role": "STAGE_ACQUISITION_INPUT",
        "stage_selection_eligible": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if any(payload.get(key) != expected for key, expected in fixed.items()):
        raise ValueError("invalid stage-acquisition safety boundary")
    cannot = payload.get("cannot_confirm")
    if not isinstance(cannot, list) or any(not isinstance(item, str) for item in cannot):
        raise ValueError("invalid stage-acquisition cannot_confirm")
    _assert_safe_tree(payload)
    return trade_date


class StageAcquisitionUniverseStore(StrictStageAcquisitionUniverseFacade, NativeDataStore):
    """Immutable run trio plus one exact-date current pointer for V2."""

    def _assert_owned_path(self, path: Path, label: str) -> None:
        """Reject path components that could redirect evidence outside ``root``."""

        if self.root.is_symlink():
            raise ValueError(f"{label} path contains symlink component")
        try:
            relative = path.relative_to(self.root)
        except ValueError as error:
            raise ValueError(f"{label} path escapes store root") from error
        current = self.root
        for part in relative.parts:
            if part in {"", ".", ".."}:
                raise ValueError(f"{label} path is not normalized")
            current = current / part
            if current.is_symlink():
                raise ValueError(f"{label} path contains symlink component")

    def _read(self, relative: str) -> Any:
        path = self._path(relative)
        self._assert_owned_path(path, f"stage-acquisition {relative}")
        return super()._read(relative)

    def _write(self, relative: str, value: Any) -> None:
        """Create one canonical file without replacement or symlink following."""

        destination = self._path(relative)
        label = f"stage-acquisition {relative}"
        self._assert_owned_path(destination, label)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._assert_owned_path(destination, label)
        handle, temporary = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(_canonical_bytes(value))
                output.flush()
                os.fsync(output.fileno())
            self._assert_owned_path(destination, label)
            os.link(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _present(path: Path) -> bool:
        return path.exists() or path.is_symlink()

    def current_path(self, trade_date: str) -> Path:
        date = _date(trade_date)
        return self._path(f"current/{date}/{ARTIFACT_ROLE}/current.json")

    def _run_dir(self, trade_date: str, run_id: str) -> Path:
        return self._path(f"runs/{trade_date}/{ARTIFACT_ROLE}/{run_id}")

    def _commit_path(self, trade_date: str, run_id: str) -> Path:
        return self._run_dir(trade_date, run_id) / "commit.json"

    def _paths(self, trade_date: str, run_id: str) -> dict[str, Path]:
        directory = self._run_dir(trade_date, run_id)
        return {
            "artifact": directory / "artifact.json",
            "manifest": directory / "manifest.json",
            "receipt": directory / "receipt.json",
        }

    def _supersession_dir(
        self,
        trade_date: str,
        expected_current_sha256: str,
        successor_artifact_sha256: str,
    ) -> Path:
        return self._path(
            f"supersessions/{trade_date}/{ARTIFACT_ROLE}/"
            f"{expected_current_sha256}-{successor_artifact_sha256}"
        )

    def _manifest_payload(
        self,
        trade_date: str,
        run_id: str,
        artifact: Mapping[str, Any],
        artifact_sha256: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": MANIFEST_SCHEMA,
            "trade_date": trade_date,
            "role": ARTIFACT_ROLE,
            "run_id": run_id,
            "status": artifact["status"],
            "row_count": artifact["row_count"],
            "codes_sha256": artifact["codes_sha256"],
            "source_projection_sha256": artifact["source_projection_sha256"],
            "artifact_sha256": artifact_sha256,
            "artifact_relative": f"runs/{trade_date}/{ARTIFACT_ROLE}/{run_id}/artifact.json",
            **{name: False for name in _FLAGS},
        }

    def _receipt_payload(
        self,
        trade_date: str,
        run_id: str,
        artifact: Mapping[str, Any],
        artifact_sha256: str,
        manifest_sha256: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": RECEIPT_SCHEMA,
            "trade_date": trade_date,
            "role": ARTIFACT_ROLE,
            "run_id": run_id,
            "status": artifact["status"],
            "row_count": artifact["row_count"],
            "codes_sha256": artifact["codes_sha256"],
            "source_projection_sha256": artifact["source_projection_sha256"],
            "artifact_sha256": artifact_sha256,
            "manifest_sha256": manifest_sha256,
            **{name: False for name in _FLAGS},
        }

    def _verify_run(self, trade_date: str, run_id: str) -> dict[str, Any]:
        paths = self._paths(trade_date, run_id)
        for name, path in paths.items():
            self._assert_owned_path(path, f"stage-acquisition {name}")
        if any(not path.is_file() for path in paths.values()):
            raise ValueError("stage-acquisition artifact, manifest, and receipt trio is incomplete")
        try:
            artifact = self._read(str(paths["artifact"].relative_to(self.root)))
            manifest = self._read(str(paths["manifest"].relative_to(self.root)))
            receipt = self._read(str(paths["receipt"].relative_to(self.root)))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("stage-acquisition evidence cannot be read") from error
        if not isinstance(artifact, Mapping) or not isinstance(manifest, Mapping) or not isinstance(receipt, Mapping):
            raise ValueError("stage-acquisition trio must contain objects")
        if validate_stage_acquisition_universe(artifact) != trade_date:
            raise ValueError("stage-acquisition artifact identity mismatch")
        expected_relative = f"runs/{trade_date}/{ARTIFACT_ROLE}/{run_id}/artifact.json"
        if (
            manifest.get("schema_version") != MANIFEST_SCHEMA
            or manifest.get("trade_date") != trade_date
            or manifest.get("role") != ARTIFACT_ROLE
            or manifest.get("run_id") != run_id
            or manifest.get("artifact_relative") != expected_relative
            or receipt.get("schema_version") != RECEIPT_SCHEMA
            or receipt.get("trade_date") != trade_date
            or receipt.get("role") != ARTIFACT_ROLE
            or receipt.get("run_id") != run_id
        ):
            raise ValueError("stage-acquisition manifest or receipt identity mismatch")
        for item in (manifest, receipt):
            if any(item.get(name) is not False for name in _FLAGS):
                raise ValueError("stage-acquisition manifest or receipt safety mismatch")
        artifact_sha256 = _digest(artifact)
        manifest_sha256 = _digest(manifest)
        receipt_sha256 = _digest(receipt)
        if (
            manifest.get("artifact_sha256") != artifact_sha256
            or receipt.get("artifact_sha256") != artifact_sha256
            or receipt.get("manifest_sha256") != manifest_sha256
            or manifest.get("row_count") != artifact.get("row_count")
            or receipt.get("row_count") != artifact.get("row_count")
            or manifest.get("codes_sha256") != artifact.get("codes_sha256")
            or receipt.get("codes_sha256") != artifact.get("codes_sha256")
            or manifest.get("source_projection_sha256") != artifact.get("source_projection_sha256")
            or receipt.get("source_projection_sha256") != artifact.get("source_projection_sha256")
            or manifest.get("status") != artifact.get("status")
            or receipt.get("status") != artifact.get("status")
        ):
            raise ValueError("stage-acquisition trio integrity mismatch")
        return {
            "run_id": run_id,
            "artifact": dict(artifact),
            "manifest": dict(manifest),
            "receipt": dict(receipt),
            "artifact_path": paths["artifact"],
            "manifest_path": paths["manifest"],
            "receipt_path": paths["receipt"],
            "artifact_sha256": artifact_sha256,
            "manifest_sha256": manifest_sha256,
            "receipt_sha256": receipt_sha256,
        }

    def _verify_physical_snapshot(
        self, artifact: Mapping[str, Any], trade_date: str
    ) -> None:
        """Bind publication to a fresh six-pool read from this data root."""

        from infrastructure.stage_acquisition_universe_contracts import (
            StageAcquisitionContractError,
            read_strict_a_preselection_snapshot,
            validate_artifact_against_snapshot,
        )

        try:
            snapshot = read_strict_a_preselection_snapshot(self.root, trade_date)
            validate_artifact_against_snapshot(artifact, snapshot)
        except (OSError, ValueError, StageAcquisitionContractError) as error:
            raise ValueError(
                f"required A pool strict physical snapshot cannot be confirmed: {error}"
            ) from error

    def _orphan_state(self, trade_date: str, selected_run: str) -> dict[str, Any] | None:
        """Find one committed run left before current, or a resumable staged run."""

        role_root = self._path(f"runs/{trade_date}/{ARTIFACT_ROLE}")
        self._assert_owned_path(role_root, "stage-acquisition orphan root")
        if not self._present(role_root):
            return None
        if not role_root.is_dir():
            raise ValueError("stage-acquisition orphan root is malformed")

        committed: list[dict[str, Any]] = []
        staged: dict[str, Any] | None = None
        for entry in sorted(role_root.iterdir(), key=lambda item: item.name):
            self._assert_owned_path(entry, "stage-acquisition orphan")
            try:
                entry_run = _safe_run_id(entry.name)
            except ValueError as error:
                raise ValueError("stage-acquisition orphan run_id is malformed") from error
            if not entry.is_dir():
                raise ValueError(f"stage-acquisition orphan {entry_run} is malformed")
            try:
                verified = self._verify_run(trade_date, entry_run)
            except ValueError as error:
                raise ValueError(
                    f"stage-acquisition orphan {entry_run} is malformed or incomplete: {error}"
                ) from error
            marker_path = self._commit_path(trade_date, entry_run)
            self._assert_owned_path(marker_path, "stage-acquisition orphan commit marker")
            if not self._present(marker_path):
                if entry_run != selected_run:
                    raise ValueError(
                        f"stage-acquisition orphan {entry_run} is incomplete"
                    )
                staged = {"kind": "staged", "verified": verified}
                continue
            try:
                marker = self._verify_commit_marker(trade_date, entry_run, verified)
            except ValueError as error:
                raise ValueError(
                    f"stage-acquisition orphan {entry_run} is malformed: {error}"
                ) from error
            committed.append(
                {"kind": "committed", "verified": {**verified, **marker}}
            )

        if staged is not None and committed:
            raise ValueError("multiple stage-acquisition orphans are ambiguous")
        if len(committed) > 1:
            raise ValueError("multiple stage-acquisition orphans are ambiguous")
        return staged or (committed[0] if committed else None)

    def _pointer_payload(
        self,
        trade_date: str,
        verified: Mapping[str, Any],
    ) -> dict[str, Any]:
        artifact = verified["artifact"]
        return {
            "schema_version": CURRENT_SCHEMA,
            "trade_date": trade_date,
            "role": ARTIFACT_ROLE,
            "run_id": verified["run_id"],
            "status": artifact["status"],
            "row_count": artifact["row_count"],
            "codes_sha256": artifact["codes_sha256"],
            "source_projection_sha256": artifact["source_projection_sha256"],
            "artifact_sha256": verified["artifact_sha256"],
            "manifest_sha256": verified["manifest_sha256"],
            "receipt_sha256": verified["receipt_sha256"],
            "artifact_relative": verified["manifest"]["artifact_relative"],
            "commit_id": verified["commit_id"],
            "commit_marker_relative": verified["commit_marker_relative"],
            "commit_marker_sha256": verified["commit_marker_sha256"],
            # The stage consumer's existing commit-marker contract requires
            # this field to remain None.  Successor ancestry is recorded in
            # the immutable supersession receipt below.
            "predecessor": None,
            **{name: False for name in _FLAGS},
        }

    def _write_current(
        self,
        trade_date: str,
        pointer: Mapping[str, Any],
        artifact_sha256: str,
        *,
        created_idempotent: bool,
    ) -> dict[str, Any]:
        pointer_path = self.current_path(trade_date)
        self._assert_owned_path(pointer_path, "stage-acquisition current pointer")
        if self._present(pointer_path):
            if not pointer_path.is_file():
                raise ValueError("stage-acquisition current pointer is not a file")
            existing = self._verify_current(trade_date)
            if existing["artifact_sha256"] == artifact_sha256:
                return self._result(existing, idempotent=True)
            raise ValueError(f"exact slot conflict: {trade_date}/{ARTIFACT_ROLE}")
        try:
            self._write(str(pointer_path.relative_to(self.root)), pointer)
        except FileExistsError:
            existing = self._verify_current(trade_date)
            if existing["artifact_sha256"] != artifact_sha256:
                raise ValueError(f"exact slot conflict: {trade_date}/{ARTIFACT_ROLE}")
            return self._result(existing, idempotent=True)
        return self._result(self._verify_current(trade_date), idempotent=created_idempotent)

    @staticmethod
    def _predecessor_payload(
        trade_date: str,
        verified: Mapping[str, Any],
        current_sha256: str,
    ) -> dict[str, Any]:
        return {
            "trade_date": trade_date,
            "run_id": verified["run_id"],
            "row_count": verified["artifact"]["row_count"],
            "codes_sha256": verified["artifact"]["codes_sha256"],
            "source_projection_sha256": verified["artifact"]["source_projection_sha256"],
            "artifact_sha256": verified["artifact_sha256"],
            "manifest_sha256": verified["manifest_sha256"],
            "receipt_sha256": verified["receipt_sha256"],
            "current_sha256": current_sha256,
            "commit_id": verified.get("commit_id"),
        }

    @staticmethod
    def _assert_successor_evolution(
        previous: Mapping[str, Any],
        successor: Mapping[str, Any],
    ) -> None:
        previous_artifact = previous["artifact"]
        successor_artifact = successor
        previous_codes = previous_artifact["codes"]
        successor_codes = successor_artifact["codes"]
        if successor_artifact["trade_date"] != previous_artifact["trade_date"]:
            raise ValueError("stage-acquisition successor date mismatch")
        if successor_artifact["source_projection_sha256"] == previous_artifact["source_projection_sha256"]:
            raise ValueError("stage-acquisition successor source projection is unchanged")
        if (
            len(successor_codes) <= len(previous_codes)
            or successor_codes[: len(previous_codes)] != previous_codes
        ):
            raise ValueError(
                "stage-acquisition successor must extend the exact-date all-A aggregate"
            )
        if successor_artifact["source_projection_row_count"] != len(successor_codes):
            raise ValueError("stage-acquisition successor source row_count mismatch")

    def _supersession_result(
        self,
        receipt: Mapping[str, Any],
        receipt_path: Path,
        *,
        idempotent: bool,
    ) -> dict[str, Any]:
        successor = receipt.get("successor")
        if not isinstance(successor, Mapping):
            raise ValueError("stage-acquisition supersession successor is invalid")
        return {
            "status": receipt["status"],
            "idempotent": idempotent,
            "trade_date": receipt["trade_date"],
            "role": ARTIFACT_ROLE,
            "run_id": successor["run_id"],
            "row_count": successor["row_count"],
            "artifact_sha256": successor["artifact_sha256"],
            "manifest_sha256": successor["manifest_sha256"],
            "receipt_sha256": successor["receipt_sha256"],
            "artifact_path": self.root / receipt["artifact_relative"],
            "manifest_path": self.root / receipt["manifest_relative"],
            "receipt_path": self.root / receipt["receipt_relative"],
            "current_path": self.root / receipt["target_current_relative"],
            "commit_id": successor.get("commit_id"),
            "commit_marker_relative": successor.get("commit_marker_relative"),
            "commit_marker_sha256": successor.get("commit_marker_sha256"),
            "predecessor": receipt.get("predecessor"),
            "supersession_receipt_path": receipt_path,
        }

    def _commit_preimage(
        self,
        trade_date: str,
        run_id: str,
        verified: Mapping[str, Any],
    ) -> dict[str, Any]:
        prefix = f"runs/{trade_date}/{ARTIFACT_ROLE}/{run_id}"
        return {
            "schema_version": COMMIT_SCHEMA,
            "trade_date": trade_date,
            "role": ARTIFACT_ROLE,
            "run_id": run_id,
            "status": COMMIT_STATUS,
            "predecessor": None,
            "row_count": verified["artifact"]["row_count"],
            "codes_sha256": verified["artifact"]["codes_sha256"],
            "source_projection_sha256": verified["artifact"]["source_projection_sha256"],
            "artifact_sha256": verified["artifact_sha256"],
            "manifest_sha256": verified["manifest_sha256"],
            "receipt_sha256": verified["receipt_sha256"],
            "artifact_relative": f"{prefix}/artifact.json",
            "manifest_relative": f"{prefix}/manifest.json",
            "receipt_relative": f"{prefix}/receipt.json",
            "current_relative": f"current/{trade_date}/{ARTIFACT_ROLE}/current.json",
        }

    def _commit_marker(
        self,
        trade_date: str,
        run_id: str,
        verified: Mapping[str, Any],
    ) -> dict[str, Any]:
        preimage = self._commit_preimage(trade_date, run_id, verified)
        return {**preimage, "commit_id": _digest(preimage)}

    def _verify_commit_marker(
        self,
        trade_date: str,
        run_id: str,
        verified: Mapping[str, Any],
    ) -> dict[str, Any]:
        marker_path = self._commit_path(trade_date, run_id)
        self._assert_owned_path(marker_path, "stage-acquisition commit marker")
        if not marker_path.is_file():
            raise ValueError("stage-acquisition commit marker is not a regular file")
        try:
            marker = self._read(str(marker_path.relative_to(self.root)))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("stage-acquisition commit marker cannot be read") from error
        expected = self._commit_marker(trade_date, run_id, verified)
        if not isinstance(marker, Mapping) or dict(marker) != expected:
            raise ValueError("stage-acquisition commit marker integrity mismatch")
        return {
            "commit": dict(marker),
            "commit_id": marker["commit_id"],
            "commit_marker_relative": str(marker_path.relative_to(self.root)),
            "commit_marker_sha256": _digest(marker),
        }

    def _ensure_commit_marker(
        self,
        trade_date: str,
        run_id: str,
        verified: Mapping[str, Any],
    ) -> dict[str, Any]:
        marker_path = self._commit_path(trade_date, run_id)
        self._assert_owned_path(marker_path, "stage-acquisition commit marker")
        relative = str(marker_path.relative_to(self.root))
        if self._present(marker_path):
            if not marker_path.is_file():
                raise ValueError("stage-acquisition commit marker is not a regular file")
            return self._verify_commit_marker(trade_date, run_id, verified)
        try:
            self._write(relative, self._commit_marker(trade_date, run_id, verified))
        except FileExistsError:
            return self._verify_commit_marker(trade_date, run_id, verified)
        return self._verify_commit_marker(trade_date, run_id, verified)

    def _verify_current(self, trade_date: str) -> dict[str, Any]:
        pointer_path = self.current_path(trade_date)
        self._assert_owned_path(pointer_path, "stage-acquisition current pointer")
        if not pointer_path.is_file():
            raise FileNotFoundError(f"exact current missing: {trade_date}/{ARTIFACT_ROLE}")
        try:
            pointer = self._read(str(pointer_path.relative_to(self.root)))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("stage-acquisition current pointer cannot be read") from error
        if not isinstance(pointer, Mapping) or pointer.get("schema_version") != CURRENT_SCHEMA:
            raise ValueError("stage-acquisition current pointer schema mismatch")
        run_id = _safe_run_id(pointer.get("run_id"))
        if pointer.get("trade_date") != trade_date or pointer.get("role") != ARTIFACT_ROLE:
            raise ValueError("stage-acquisition current pointer identity mismatch")
        if any(pointer.get(name) is not False for name in _FLAGS):
            raise ValueError("stage-acquisition current pointer safety mismatch")
        marker_fields = [name in pointer for name in _COMMIT_POINTER_FIELDS]
        if any(marker_fields) and not all(marker_fields):
            raise ValueError("stage-acquisition current commit marker fields are partial")
        has_marker = all(marker_fields)
        predecessor = pointer.get("predecessor")
        if predecessor is not None and not isinstance(predecessor, Mapping):
            raise ValueError("stage-acquisition current predecessor is invalid")
        verified = self._verify_run(trade_date, run_id)
        expected = {
            "status": verified["receipt"]["status"],
            "row_count": verified["receipt"]["row_count"],
            "codes_sha256": verified["artifact"]["codes_sha256"],
            "source_projection_sha256": verified["artifact"]["source_projection_sha256"],
            "artifact_sha256": verified["artifact_sha256"],
            "manifest_sha256": verified["manifest_sha256"],
            "receipt_sha256": verified["receipt_sha256"],
            "artifact_relative": verified["manifest"]["artifact_relative"],
        }
        marker_verified = None
        if has_marker:
            marker_verified = self._verify_commit_marker(trade_date, run_id, verified)
            expected.update(
                {
                    "commit_id": marker_verified["commit_id"],
                    "commit_marker_relative": marker_verified["commit_marker_relative"],
                    "commit_marker_sha256": marker_verified["commit_marker_sha256"],
                    "predecessor": predecessor,
                }
            )
        if any(pointer.get(key) != value for key, value in expected.items()):
            raise ValueError("stage-acquisition current pointer integrity mismatch")
        return {
            "current": dict(pointer),
            **verified,
            **(marker_verified or {}),
            "current_path": pointer_path,
        }

    def publish_legacy_v2(self, payload: Mapping[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
        trade_date = validate_stage_acquisition_universe(payload)
        artifact = deepcopy(dict(payload))
        artifact_sha256 = _digest(artifact)
        selected_run = _safe_run_id(
            run_id or f"{trade_date}-{ARTIFACT_ROLE.lower()}-{artifact_sha256[:12]}"
        )
        paths = self._paths(trade_date, selected_run)
        manifest = self._manifest_payload(trade_date, selected_run, artifact, artifact_sha256)
        manifest_sha256 = _digest(manifest)
        receipt = self._receipt_payload(
            trade_date, selected_run, artifact, artifact_sha256, manifest_sha256
        )
        with self._lock():
            self._verify_physical_snapshot(artifact, trade_date)
            pointer_path = self.current_path(trade_date)
            self._assert_owned_path(pointer_path, "stage-acquisition current pointer")
            paths_to_check = (*paths.values(), self._commit_path(trade_date, selected_run))
            for path in paths_to_check:
                self._assert_owned_path(path, "stage-acquisition publish")
            if self._present(pointer_path):
                if not pointer_path.is_file():
                    raise ValueError("stage-acquisition current pointer is not a file")
                existing = self._verify_current(trade_date)
                if existing["artifact_sha256"] == artifact_sha256:
                    return self._result(existing, idempotent=True)
                raise ValueError(f"exact slot conflict: {trade_date}/{ARTIFACT_ROLE}")

            orphan = self._orphan_state(trade_date, selected_run)
            if orphan is not None and orphan["kind"] == "committed":
                orphan_verified = orphan["verified"]
                if orphan_verified["artifact_sha256"] != artifact_sha256:
                    raise ValueError(f"exact slot conflict: {trade_date}/{ARTIFACT_ROLE}")
                pointer = self._pointer_payload(trade_date, orphan_verified)
                return self._write_current(
                    trade_date,
                    pointer,
                    artifact_sha256,
                    created_idempotent=orphan_verified["run_id"] != selected_run,
                )
            if orphan is not None and orphan["verified"]["artifact_sha256"] != artifact_sha256:
                raise ValueError(f"exact slot conflict: {trade_date}/{ARTIFACT_ROLE}")

            paths["artifact"].parent.mkdir(parents=True, exist_ok=True)
            self._ensure_file(
                paths["artifact"],
                artifact,
                conflict_message="stage-acquisition immutable artifact conflict",
            )
            self._ensure_file(paths["manifest"], manifest)
            self._ensure_file(paths["receipt"], receipt)
            verified = self._verify_run(trade_date, selected_run)
            marker_verified = self._ensure_commit_marker(
                trade_date, selected_run, verified
            )
            verified["commit"] = marker_verified["commit"]
            verified["commit_id"] = marker_verified["commit_id"]
            verified["commit_marker_relative"] = marker_verified["commit_marker_relative"]
            verified["commit_marker_sha256"] = marker_verified["commit_marker_sha256"]
            pointer = self._pointer_payload(trade_date, verified)
            result = self._write_current(
                trade_date,
                pointer,
                artifact_sha256,
                created_idempotent=False,
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
        """Publish only through the strict V3 successor authority.

        The old V2 successor protocol remains available under its explicit
        ``publish_legacy_v2_successor`` name.  Keeping the public method
        strict prevents an omitted identity from silently selecting a
        different current path and digest contract.
        """

        if identity is None:
            raise StrictCommitError(
                "strict successor publication requires evidence identity"
            )
        return super().publish_successor(
            payload,
            expected_current_sha256=expected_current_sha256,
            reason=reason,
            run_id=run_id,
            identity=identity,
        )

    def publish_legacy_v2_successor(
        self,
        payload: Mapping[str, Any],
        *,
        expected_current_sha256: str,
        reason: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Publish the historical V2 successor for explicit offline callers.

        This method is intentionally not part of the strict authority and
        accepts only the V2 artifact/current contract.  In particular, its
        artifact digest remains a legacy payload identifier, never a strict
        raw-current CAS token.
        """

        trade_date = validate_stage_acquisition_universe(payload)
        artifact = deepcopy(dict(payload))
        successor_sha = _digest(artifact)
        expected = str(expected_current_sha256 or "").lower()
        reason = str(reason or "").strip()
        if not _DIGEST_RE.fullmatch(expected):
            raise ValueError("expected_current_sha256 must be a 64-hex SHA256")
        if not reason:
            raise ValueError("reason is required for stage-acquisition successor")
        selected_run = _safe_run_id(
            run_id or f"{trade_date}-{ARTIFACT_ROLE.lower()}-{successor_sha[:12]}"
        )
        paths = self._paths(trade_date, selected_run)
        manifest = self._manifest_payload(trade_date, selected_run, artifact, successor_sha)
        receipt = self._receipt_payload(
            trade_date, selected_run, artifact, successor_sha, _digest(manifest)
        )

        with self._lock():
            self._verify_physical_snapshot(artifact, trade_date)
            pointer_path = self.current_path(trade_date)
            self._assert_owned_path(pointer_path, "stage-acquisition current pointer")
            if not pointer_path.is_file():
                raise ValueError("stage-acquisition current pointer is missing")
            current_bytes = pointer_path.read_bytes()
            current_sha = hashlib.sha256(current_bytes).hexdigest()
            current = self._verify_current(trade_date)
            if expected == current["artifact_sha256"]:
                raise ValueError(
                    "stage-acquisition artifact SHA is not a current CAS token"
                )
            supersession_dir = self._supersession_dir(trade_date, expected, successor_sha)
            supersession_path = supersession_dir / "receipt.json"
            if supersession_path.is_file():
                prior = self._read(str(supersession_path.relative_to(self.root)))
                if (
                    not isinstance(prior, Mapping)
                    or prior.get("schema_version") != SUPERSESSION_SCHEMA
                    or prior.get("trade_date") != trade_date
                    or prior.get("role") != ARTIFACT_ROLE
                    or prior.get("status") != "SUPERSEDED"
                    or prior.get("reason") != reason
                    or prior.get("expected_current_sha256") != expected
                    or prior.get("successor_artifact_sha256") != successor_sha
                ):
                    raise ValueError("stage-acquisition supersession receipt conflict")
                if current["artifact_sha256"] == successor_sha:
                    return self._supersession_result(prior, supersession_path, idempotent=True)
                if current["artifact_sha256"] != prior.get("previous_artifact_sha256"):
                    raise ValueError("stage-acquisition supersession predecessor changed")
                successor_pointer = self._read(prior["successor_current_relative"])
                if not isinstance(successor_pointer, Mapping) or current_sha != prior.get("previous_current_sha256"):
                    raise ValueError("stage-acquisition supersession evidence is invalid")
                super()._write(str(pointer_path.relative_to(self.root)), successor_pointer)
                return self._supersession_result(prior, supersession_path, idempotent=True)

            if current["artifact_sha256"] == successor_sha:
                if expected != current_sha:
                    raise ValueError("stage-acquisition current SHA does not match expected CAS")
                return self._result(current, idempotent=True)
            if expected != current_sha:
                raise ValueError("stage-acquisition current SHA mismatch")
            if selected_run == current["run_id"]:
                raise ValueError("stage-acquisition successor run_id equals current run")
            self._assert_successor_evolution(current, artifact)

            paths["artifact"].parent.mkdir(parents=True, exist_ok=True)
            self._ensure_file(paths["artifact"], artifact, conflict_message="stage-acquisition immutable successor artifact conflict")
            self._ensure_file(paths["manifest"], manifest, conflict_message="stage-acquisition immutable successor manifest conflict")
            self._ensure_file(paths["receipt"], receipt, conflict_message="stage-acquisition immutable successor receipt conflict")
            verified = self._verify_run(trade_date, selected_run)
            predecessor = self._predecessor_payload(trade_date, current, current_sha)
            marker = self._ensure_commit_marker(trade_date, selected_run, verified)
            verified.update(
                commit=marker["commit"],
                commit_id=marker["commit_id"],
                commit_marker_relative=marker["commit_marker_relative"],
                commit_marker_sha256=marker["commit_marker_sha256"],
            )
            pointer = self._pointer_payload(trade_date, verified)
            successor_pointer = supersession_dir / "successor-current.json"
            self._ensure_file(
                successor_pointer,
                pointer,
                conflict_message="stage-acquisition successor current evidence conflict",
            )
            supersession = {
                "schema_version": SUPERSESSION_SCHEMA,
                "trade_date": trade_date,
                "role": ARTIFACT_ROLE,
                "status": "SUPERSEDED",
                "evolution": "EXACT_DATE_ALL_A_AGGREGATE_EXTENSION",
                "reason": reason,
                "expected_current_sha256": expected,
                "previous_current_sha256": current_sha,
                "successor_current_sha256": hashlib.sha256(_canonical_bytes(pointer)).hexdigest(),
                "previous_run_id": current["run_id"],
                "successor_run_id": selected_run,
                "previous_row_count": current["artifact"]["row_count"],
                "successor_row_count": artifact["row_count"],
                "previous_artifact_sha256": current["artifact_sha256"],
                "successor_artifact_sha256": successor_sha,
                "predecessor": predecessor,
                "successor": {
                    "run_id": selected_run,
                    "row_count": artifact["row_count"],
                    "codes_sha256": artifact["codes_sha256"],
                    "source_projection_sha256": artifact["source_projection_sha256"],
                    "artifact_sha256": successor_sha,
                    "manifest_sha256": verified["manifest_sha256"],
                    "receipt_sha256": verified["receipt_sha256"],
                    "commit_id": marker["commit_id"],
                    "commit_marker_relative": marker["commit_marker_relative"],
                },
                "artifact_relative": str(paths["artifact"].relative_to(self.root)),
                "manifest_relative": str(paths["manifest"].relative_to(self.root)),
                "receipt_relative": str(paths["receipt"].relative_to(self.root)),
                "successor_current_relative": str(successor_pointer.relative_to(self.root)),
                "target_current_relative": str(pointer_path.relative_to(self.root)),
                **{name: False for name in _FLAGS},
            }
            self._ensure_file(supersession_path, supersession, conflict_message="stage-acquisition supersession receipt conflict")
            if hashlib.sha256(pointer_path.read_bytes()).hexdigest() != current_sha:
                raise ValueError("stage-acquisition current changed during successor CAS")
            super()._write(str(pointer_path.relative_to(self.root)), pointer)
            return self._supersession_result(supersession, supersession_path, idempotent=False)

    def _ensure_file(
        self,
        path: Path,
        expected: Mapping[str, Any],
        *,
        conflict_message: str = "stage-acquisition immutable evidence conflict",
    ) -> None:
        self._assert_owned_path(path, "stage-acquisition evidence")
        relative = str(path.relative_to(self.root))
        if self._present(path):
            if not path.is_file() or self._read(relative) != dict(expected):
                raise ValueError(conflict_message)
            return
        try:
            self._write(relative, expected)
        except FileExistsError:
            self._assert_owned_path(path, "stage-acquisition evidence")
            if not path.is_file() or self._read(relative) != dict(expected):
                raise ValueError(conflict_message)

    @staticmethod
    def _result(verified: Mapping[str, Any], *, idempotent: bool) -> dict[str, Any]:
        return {
            "status": verified["receipt"]["status"],
            "idempotent": idempotent,
            "trade_date": verified["receipt"]["trade_date"],
            "role": ARTIFACT_ROLE,
            "run_id": verified["run_id"],
            "row_count": verified["receipt"]["row_count"],
            "artifact_sha256": verified["artifact_sha256"],
            "manifest_sha256": verified["manifest_sha256"],
            "receipt_sha256": verified["receipt_sha256"],
            "artifact_path": verified["artifact_path"],
            "manifest_path": verified["manifest_path"],
            "receipt_path": verified["receipt_path"],
            "current_path": verified.get("current_path") or None,
            "commit_id": verified.get("commit_id"),
            "commit_marker_relative": verified.get("commit_marker_relative"),
            "commit_marker_sha256": verified.get("commit_marker_sha256"),
            "predecessor": verified.get("current", {}).get("predecessor"),
        }

    def read_verified(self, trade_date: str) -> dict[str, Any]:
        date = _date(trade_date)
        return self._verify_current(date)

__all__ = [
    "ARTIFACT_ROLE",
    "ARTIFACT_VERSION",
    "COMMIT_MARKER_SCHEMA",
    "COMMIT_SCHEMA",
    "COMMIT_STATUS",
    "CURRENT_SCHEMA",
    "MANIFEST_SCHEMA",
    "RECEIPT_SCHEMA",
    "SCHEMA_VERSION",
    "SUPERSESSION_SCHEMA",
    "StageAcquisitionUniverseStore",
    "build_stage_acquisition_universe",
    "validate_stage_acquisition_universe",
]
