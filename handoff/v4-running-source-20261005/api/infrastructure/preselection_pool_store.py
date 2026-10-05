"""Independent, exact-date storage for V3.5 preselection pools."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

from infrastructure.data_store import _canonical_bytes, _date, _sha256
from infrastructure.interprocess_lock import owned_interprocess_lock
from infrastructure.owned_path import resolve_owned_path
from infrastructure.owned_io import SafeRoot
from infrastructure.trading_safety import assert_safe_tree


POOL_ORDER = (
    "a_d1_premarket_pool",
    "a_d1_fupan_watchlist_pool",
    "a_d1_stage7_fenshi_review_pool",
    "a_share_research_recommendation_pool",
    "a_share_baimao_research_map",
    "hkconnect_d1_top100",
    "wechat_public_account_v3_preselect",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

# The original pool contract used three coarse roles.  Formal 20260824/25
# artifacts already carry these producer-specific roles, so readers must
# accept them without weakening the legacy final-output rejection.
FORMAL_SOURCE_ROLES = frozenset(
    {
        "SHARED_VERIFIED_V192",
        "VERIFIED_D1_FUPAN_REVIEW",
        "VERIFIED_D1_STAGE7_REPLAY",
        "VERIFIED_HOURLY_RESEARCH",
        "SHARED_VERIFIED_HK_0_2",
        "VERIFIED_WECHAT_RESEARCH",
        "VERIFIED_BAIMAO_RESEARCH",
    }
)

# These are the lineage additions present on the accepted formal artifacts.
# They remain optional so the generic v1 artifacts and their receipts keep
# their exact historical wire shape.
POOL_ARTIFACT_OPTIONAL_FIELDS = frozenset(
    {
        "artifact_role",
        "artifact_version",
        "signal_date",
        "target_date",
        "source_artifact_sha256",
        "source_merge_role",
        "source_row_count",
        "source_run_id",
        "stage_selection_eligible",
        "source_manifest_sha256", "source_receipt_sha256", "source_archive",
        "historical_provenance", "coverage_evidence",
    }
)
RECEIPT_EXTENSION_FIELDS = frozenset({"source_row_count", "source_run_id"})


class PreselectionPoolStore:
    """Store each graph-defined pool as its own immutable artifact."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._io = SafeRoot(self.root)
        # Capture an already-existing root before any caller can swap its
        # directory entry.  A missing root remains constructible for the
        # first materialization, where SafeRoot binds it on the first write.
        try:
            with self._io.directory():
                pass
        except FileNotFoundError:
            pass

    def _path(self, relative: str) -> Path:
        return resolve_owned_path(self.root, relative)

    def _read(self, relative: str) -> Any:
        import json

        return json.loads(self._io.read_bytes(relative).decode("utf-8"))

    def _write(self, relative: str, value: Mapping[str, Any]) -> None:
        # Payload contracts stay at each public materialization boundary.
        self._io.write_bytes(relative, _canonical_bytes(value))

    @staticmethod
    def _relative(trade_date: str, pool_id: str) -> tuple[str, str]:
        return (
            f"preselection_pools/{trade_date}/{pool_id}.json",
            f"preselection_pools/{trade_date}/receipts/{pool_id}.json",
        )

    @staticmethod
    def _receipt(
        *,
        trade_date: str,
        pool_id: str,
        artifact_path: str,
        artifact_sha256: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        receipt = {
            "schema_version": "v3_5.preselection_pool_receipt.v1",
            "trade_date": trade_date,
            "pool_id": pool_id,
            "artifact_path": artifact_path,
            "artifact_sha256": artifact_sha256,
            "source_sha256": payload["source_sha256"],
            "source_role": payload["source_role"],
        }
        for key in RECEIPT_EXTENSION_FIELDS:
            if key in payload:
                receipt[key] = payload[key]
        return receipt

    def materialize(self, payload: Mapping[str, Any]) -> dict[str, str]:
        from infrastructure.historical_pool_sources import guard_v192_payload
        guard_v192_payload(self.root, payload)
        # Physical pool writers and strict stage publication share this root
        # lock.  This closes the snapshot-to-commit window for every writer
        # using the store API without creating a second lock protocol.
        with owned_interprocess_lock(
            self.root / ".import.lock",
            timeout_seconds=10,
            timeout_message="data-root import lock timeout",
        ):
            return self._materialize_unlocked(payload)

    def _materialize_unlocked(self, payload: Mapping[str, Any]) -> dict[str, str]:
        trade_date = validate_pool_artifact(payload)
        pool_id = str(payload["pool_id"])
        artifact_path, receipt_path = self._relative(trade_date, pool_id)
        manifest_path = f"preselection_pools/{trade_date}/manifest.json"
        digest = _sha256(payload)
        receipt = self._receipt(
            trade_date=trade_date,
            pool_id=pool_id,
            artifact_path=artifact_path,
            artifact_sha256=digest,
            payload=payload,
        )
        manifest_file = self._path(manifest_path)
        manifest = self._read(manifest_path) if manifest_file.is_file() else {}
        if not isinstance(manifest, dict):
            raise ValueError("invalid preselection-pool manifest")
        existing = manifest.get(pool_id)
        artifact_file = self._path(artifact_path)
        receipt_file = self._path(receipt_path)
        if existing is not None:
            if (
                existing != digest
                or not artifact_file.is_file()
                or _sha256(self._read(artifact_path)) != digest
                or not receipt_file.is_file()
                or self._read(receipt_path) != receipt
            ):
                raise ValueError("conflicting preselection-pool materialization")
            return {"artifact_path": artifact_path, "receipt_path": receipt_path, "sha256": digest}
        if artifact_file.exists() or receipt_file.exists():
            raise ValueError("partial preselection-pool materialization")
        self._write(artifact_path, payload)
        self._write(receipt_path, receipt)
        manifest[pool_id] = digest
        self._write(manifest_path, manifest)
        return {"artifact_path": artifact_path, "receipt_path": receipt_path, "sha256": digest}

    def recover_v192_original(self, source_dir: Path, *, signal_date: str,
                              target_date: str, expected_sha256: str,
                              expected_original_sha256: Mapping[str, str] | None = None) -> dict[str, Any]:
        """CAS recovery from approved bytes only; never accept a caller-built pool."""
        from infrastructure.historical_pool_sources import (
            archive_original, check_dates, require_external_original_sha, v192_payload,
        )
        check_dates(signal_date, target_date)
        require_external_original_sha("v192", signal_date, target_date, expected_original_sha256)
        archive_original(self.root, source_dir, "v192", signal_date=signal_date, target_date=target_date,
                         expected_original_sha256=expected_original_sha256)
        return self._recover_0918_original(v192_payload(self.root, signal_date, target_date), expected_sha256)

    def _recover_0918_original(self, payload: Mapping[str, Any],
                              expected_sha256: str) -> dict[str, Any]:
        """Bounded owner recovery using existing immutable revisions + manifest commit.

        A retry repairs the *manifest-committed* pair first. No reader is asked to
        trust a half-written trio. Only EXPECTED_MISSING -> exact-source recovery
        is authorized; another valid nonempty/dirty pool is never overwritten.
        """
        from infrastructure.historical_pool_sources import guard_v192_payload
        # Legacy method name retained for existing reviewed callers.
        from infrastructure.historical_pool_sources import approved
        if payload.get("pool_id") not in {
            "a_d1_premarket_pool", "a_d1_stage7_fenshi_review_pool"
        }:
            raise ValueError("historical recovery scope mismatch")
        approved("v192" if payload["pool_id"] == "a_d1_premarket_pool" else "stage7",
                 payload.get("signal_date"), payload.get("trade_date"))
        validate_pool_artifact(payload)
        guard_v192_payload(self.root, payload)
        if payload["pool_id"] == "a_d1_stage7_fenshi_review_pool":
            from infrastructure.historical_pool_sources import validate_native_stage7
            validate_native_stage7(self.root, payload)
        if not _SHA256.fullmatch(str(expected_sha256)) and not (
            expected_sha256 == "ABSENT" and payload["pool_id"] == "a_d1_stage7_fenshi_review_pool"
        ):
            raise ValueError("recovery requires the observed committed artifact SHA")
        # API/stage writers share the existing data-root import lock.
        with owned_interprocess_lock(self.root / ".import.lock", timeout_seconds=10,
                                     timeout_message="data-root import lock timeout"):
            return self._recover_0918_original_locked(payload, expected_sha256)

    def _recover_0918_original_locked(self, payload: Mapping[str, Any],
                                     expected_sha256: str) -> dict[str, Any]:
        date, pool = payload["trade_date"], payload["pool_id"]
        artifact_path, receipt_path = self._relative(date, pool)
        manifest_path = f"preselection_pools/{date}/manifest.json"
        try:
            manifest = self._read(manifest_path)
        except FileNotFoundError:
            manifest = {}
        if not isinstance(manifest, dict):
            raise ValueError("invalid recovery manifest")
        digest = _sha256(payload)
        if pool not in manifest and expected_sha256 == "ABSENT":
            new_receipt = self._receipt(trade_date=date, pool_id=pool, artifact_path=artifact_path,
                                       artifact_sha256=digest, payload=payload)
            # An absent slot may contain only our same interrupted first import.
            # A foreign untracked artifact/receipt is dirty, never disposable.
            for path, value in ((artifact_path, payload), (receipt_path, new_receipt)):
                try:
                    pending = self._read(path)
                except FileNotFoundError:
                    continue
                if pending != dict(value):
                    raise ValueError("untracked dirty recovery file cannot be overwritten")
            self._save_recovery_revision(date, pool, digest, payload, new_receipt)
            self._write(artifact_path, payload)
            self._write(receipt_path, new_receipt)
            manifest[pool] = digest
            self._write(manifest_path, manifest)
            self.read_pool_snapshot(date, pool)
            return {"artifact_path": artifact_path, "receipt_path": receipt_path,
                    "sha256": digest, "status": payload["status"], "idempotent": False}
        if not _SHA256.fullmatch(str(manifest.get(pool))):
            raise ValueError("recovery requires an existing committed placeholder")
        committed = manifest[pool]
        if committed not in {expected_sha256, digest}:
            raise ValueError("recovery compare-and-swap conflict")
        # Existing revision layout is the recovery authority, not a new journal.
        revision = f"preselection_revisions/{date}/{committed}.json"
        try:
            current = self.read_pool(date, pool)
        except (OSError, ValueError, KeyError, TypeError):
            current = self._read(revision)
            if _sha256(current) != committed or validate_pool_artifact(current) != date or current.get("pool_id") != pool:
                raise ValueError("committed recovery revision identity mismatch")
            expected_receipt = self._receipt(trade_date=date, pool_id=pool,
                artifact_path=artifact_path, artifact_sha256=committed, payload=current)
            revision_receipt = self._read(revision.removesuffix('.json') + '.receipt.json')
            if revision_receipt != self._recovery_revision_receipt(date, pool, committed, current, expected_receipt):
                raise ValueError("committed recovery revision receipt mismatch")
            self._write(artifact_path, current)
            self._write(receipt_path, expected_receipt)
            self.read_pool_snapshot(date, pool)  # physical trio must agree before retry
        if committed == digest:
            if dict(current) != dict(payload):
                raise ValueError("idempotent recovery payload mismatch")
            return {"artifact_path": artifact_path, "receipt_path": receipt_path,
                    "sha256": digest, "status": payload["status"], "idempotent": True}
        if not (current.get("source_role") == "EXPECTED_MISSING" and
                current.get("producer_id") == "graph_expected_missing_v1" and
                current.get("status") == "CANNOT_CONFIRM" and current.get("rows") == [] and
                current.get("source_path") == "" and
                current.get("source_sha256") == hashlib.sha256(b"").hexdigest() and
                current.get("cannot_confirm") and
                all(current.get(flag) is False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))):
            raise ValueError("recovery cannot replace a non-placeholder or dirty pool")
        old_receipt = self._receipt(trade_date=date, pool_id=pool, artifact_path=artifact_path,
                                   artifact_sha256=committed, payload=current)
        new_receipt = self._receipt(trade_date=date, pool_id=pool, artifact_path=artifact_path,
                                   artifact_sha256=digest, payload=payload)
        self._save_recovery_revision(date, pool, committed, current, old_receipt)
        self._save_recovery_revision(date, pool, digest, payload, new_receipt)
        self._write(artifact_path, payload)
        self._write(receipt_path, new_receipt)
        manifest[pool] = digest  # sole commit marker, written last
        self._write(manifest_path, manifest)
        snapshot = self.read_pool_snapshot(date, pool)
        if snapshot["artifact"] != dict(payload):
            raise ValueError("recovery readback mismatch")
        return {"artifact_path": artifact_path, "receipt_path": receipt_path,
                "sha256": digest, "status": payload["status"], "idempotent": False}

    @staticmethod
    def _recovery_revision_receipt(date, pool, digest, payload, receipt):
        return {"schema_version": "v3_5.preselection_pool_revision_receipt.v1",
                "trade_date": date, "pool_id": pool,
                "artifact_path": f"preselection_revisions/{date}/{digest}.json",
                "artifact_sha256": digest, "source_sha256": payload.get("source_sha256"),
                "source_role": payload.get("source_role"), "latest_receipt": dict(receipt)}

    def _save_recovery_revision(self, date, pool, digest, payload, receipt):
        """Complete interrupted immutable revision creation, without overwriting bytes."""
        artifact = f"preselection_revisions/{date}/{digest}.json"
        revision_receipt = self._recovery_revision_receipt(date, pool, digest, payload, receipt)
        for path, value in ((artifact, payload),
                            (artifact.removesuffix('.json') + '.receipt.json', revision_receipt)):
            try:
                existing = self._read(path)
            except FileNotFoundError:
                self._write(path, value)
            else:
                if existing != dict(value):
                    raise ValueError("conflicting immutable recovery revision")

    def read_pool(self, trade_date: str, pool_id: str) -> dict[str, Any]:
        trade_date = _date(trade_date)
        if pool_id not in POOL_ORDER:
            raise ValueError("unknown preselection pool")
        artifact_path, receipt_path = self._relative(trade_date, pool_id)
        manifest_path = f"preselection_pools/{trade_date}/manifest.json"
        if not self._path(artifact_path).is_file():
            raise FileNotFoundError(pool_id)
        payload = self._read(artifact_path)
        digest = _sha256(payload)
        manifest = self._read(manifest_path)
        receipt = self._read(receipt_path)
        expected = self._receipt(
            trade_date=trade_date,
            pool_id=pool_id,
            artifact_path=artifact_path,
            artifact_sha256=digest,
            payload=payload,
        )
        if (
            not isinstance(manifest, dict)
            or manifest.get(pool_id) != digest
            or receipt != expected
        ):
            raise ValueError("preselection-pool manifest or receipt SHA mismatch")
        if validate_pool_artifact(payload) != trade_date or payload["pool_id"] != pool_id:
            raise ValueError("preselection-pool identity mismatch")
        return payload

    def read_pool_snapshot(self, trade_date: str, pool_id: str) -> dict[str, Any]:
        """Read one pool trio with canonical physical-byte identity.

        ``read_pool`` intentionally keeps its historical semantic-object
        behavior.  Strict stage acquisition needs the physical artifact,
        manifest, and receipt bytes to be canonical and bound to one another.
        This reader therefore returns both semantic and raw-byte digests while
        preserving the existing store paths and validation rules.
        """

        trade_date = _date(trade_date)
        if pool_id not in POOL_ORDER:
            raise ValueError("unknown preselection pool")
        artifact_relative, receipt_relative = self._relative(trade_date, pool_id)
        manifest_relative = f"preselection_pools/{trade_date}/manifest.json"
        try:
            # The descriptor-anchored reader both rejects symlink races and
            # rechecks the root identity captured by SafeRoot.__init__.
            artifact_bytes = self._io.read_bytes(artifact_relative)
            manifest_bytes = self._io.read_bytes(manifest_relative)
            receipt_bytes = self._io.read_bytes(receipt_relative)
        except FileNotFoundError as error:
            raise FileNotFoundError(
                "preselection-pool physical snapshot file is missing"
            ) from error
        try:
            artifact = json.loads(artifact_bytes.decode("utf-8"))
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            receipt = json.loads(receipt_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("preselection-pool physical JSON cannot be parsed") from error
        if not isinstance(artifact, Mapping) or not isinstance(manifest, Mapping) or not isinstance(receipt, Mapping):
            raise ValueError("preselection-pool physical snapshot must contain objects")
        if artifact_bytes != _canonical_bytes(artifact):
            raise ValueError("preselection-pool artifact bytes are not canonical")
        if manifest_bytes != _canonical_bytes(manifest):
            raise ValueError("preselection-pool manifest bytes are not canonical")
        if receipt_bytes != _canonical_bytes(receipt):
            raise ValueError("preselection-pool receipt bytes are not canonical")

        digest = _sha256(artifact)
        expected_receipt = self._receipt(
            trade_date=trade_date,
            pool_id=pool_id,
            artifact_path=artifact_relative,
            artifact_sha256=digest,
            payload=artifact,
        )
        if manifest.get(pool_id) != digest or receipt != expected_receipt:
            raise ValueError("preselection-pool manifest or receipt SHA mismatch")
        if validate_pool_artifact(artifact) != trade_date or artifact.get("pool_id") != pool_id:
            raise ValueError("preselection-pool identity mismatch")
        return {
            "artifact": dict(artifact),
            "payload": dict(artifact),
            "manifest": dict(manifest),
            "receipt": dict(receipt),
            "artifact_relative": artifact_relative,
            "manifest_relative": manifest_relative,
            "receipt_relative": receipt_relative,
            "artifact_relative_path": artifact_relative,
            "manifest_relative_path": manifest_relative,
            "receipt_relative_path": receipt_relative,
            "pool_sha256": digest,
            "semantic_sha256": digest,
            "artifact_sha256": digest,
            "artifact_raw_sha256": _sha256_bytes(artifact_bytes),
            "manifest_raw_sha256": _sha256_bytes(manifest_bytes),
            "receipt_raw_sha256": _sha256_bytes(receipt_bytes),
        }

    read_pool_raw_snapshot = read_pool_snapshot
    read_raw_snapshot = read_pool_snapshot

    def read_all(self, trade_date: str) -> list[dict[str, Any]]:
        trade_date = _date(trade_date)
        pools: list[dict[str, Any]] = []
        for pool_id in POOL_ORDER:
            try:
                pools.append(self.read_pool(trade_date, pool_id))
            except FileNotFoundError:
                continue
        if not pools:
            raise FileNotFoundError(trade_date)
        return pools



class PreselectionSourceResolver:
    """Read-only exact-date ownership; publication always stays with its owner.

    A primary date directory (even incomplete) cannot be shadowed by another
    root.  This is whole-date routing, never per-pool merging or latest fallback.
    Existing stores retain all artifact/manifest/receipt and path checks.
    """

    def __init__(self, root: Path | str, *, source_root: Path | str | None = None) -> None:
        self.root = Path(os.path.abspath(Path(root).expanduser()))
        self.source_root = (
            Path(os.path.abspath(Path(source_root).expanduser()))
            if source_root is not None else None
        )
        self._stores = {self.root: PreselectionPoolStore(self.root)}
        if self.source_root is not None and self.source_root != self.root:
            self._stores[self.source_root] = PreselectionPoolStore(self.source_root)

    def root_for_date(self, trade_date: str) -> Path:
        date = _date(trade_date)
        for root in self._stores:
            # Reject a link in either component, including dangling links.
            # SafeRoot still rechecks descriptor/root identity on the read.
            parent = root / "preselection_pools"
            child = parent / date
            if parent.is_symlink() or child.is_symlink():
                raise ValueError("preselection date ownership cannot use symlinks")
            if parent.exists() and not parent.is_dir():
                raise ValueError("preselection source parent is not a directory")
            if child.exists():
                if not child.is_dir():
                    raise ValueError("preselection date source is not a directory")
                return root
        return self.root  # An exact missing date stays missing, not latest.

    def read_pool_snapshot(self, trade_date: str, pool_id: str) -> dict[str, Any]:
        root = self.root_for_date(trade_date)
        try:
            result = self._stores[root].read_pool_snapshot(trade_date, pool_id)
        except (KeyError, TypeError) as error:
            # The original receipt builder indexes required source fields.
            # An incomplete physical object is unavailable, never HTTP 500
            # and never permission to search a different root.
            raise ValueError("preselection-pool required identity fields invalid") from error
        if self.root_for_date(trade_date) != root:
            raise ValueError("preselection date owner changed during read")
        return {**result, "physical_source_root": str(root)}

    def read_pool(self, trade_date: str, pool_id: str) -> dict[str, Any]:
        return self.read_pool_snapshot(trade_date, pool_id)["artifact"]

    def read_all(self, trade_date: str) -> list[dict[str, Any]]:
        date = _date(trade_date)
        root = self.root_for_date(date)
        rows: list[dict[str, Any]] = []
        for pool_id in POOL_ORDER:
            try:
                rows.append(self.read_pool(date, pool_id))
            except FileNotFoundError:
                continue
        if self.root_for_date(date) != root:
            raise ValueError("preselection date owner changed during read")
        if not rows:
            raise FileNotFoundError(date)
        return rows

    def verified_dates(self) -> tuple[str, ...]:
        candidates: set[str] = set()
        for root in self._stores:
            parent = root / "preselection_pools"
            if parent.is_symlink():
                continue
            try:
                candidates.update(child.name for child in parent.iterdir())
            except (FileNotFoundError, NotADirectoryError):
                continue
        verified: list[str] = []
        for date in sorted(candidates):
            for pool_id in POOL_ORDER:
                try:
                    self.read_pool_snapshot(date, pool_id)
                except (OSError, ValueError):
                    continue
                verified.append(date)
                break
        return tuple(verified)


def validate_pool_artifact(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise ValueError("invalid preselection-pool artifact")
    required = {
        "schema_version", "trade_date", "pool_id", "display_name", "market",
        "status", "producer_id", "source_role", "source_path", "source_sha256",
        "rows", "cannot_confirm", "production_allowed", "buy_gate_updated", "orders_sent",
    }
    missing = required - set(payload)
    if missing:
        raise ValueError("missing required preselection-pool fields")
    unknown = set(payload) - required - POOL_ARTIFACT_OPTIONAL_FIELDS
    if unknown:
        raise ValueError("invalid preselection-pool fields")
    if payload.get("schema_version") != "v3_5.preselection_pool.v1":
        raise ValueError("invalid preselection-pool schema")
    trade_date = _date(str(payload.get("trade_date") or ""))
    pool_id = str(payload.get("pool_id") or "")
    if pool_id not in POOL_ORDER or pool_id == "legacy_partial_migration":
        raise ValueError("unknown or legacy preselection pool")
    if payload.get("source_role") == "LEGACY_FINAL_API":
        raise ValueError("legacy final API is oracle-only")
    if payload.get("source_role") not in {
        "RAW_SOURCE",
        "UPSTREAM_PRODUCER_ARTIFACT",
        "EXPECTED_MISSING",
        *FORMAL_SOURCE_ROLES,
    }:
        raise ValueError("invalid preselection source role")
    if not _SHA256.fullmatch(str(payload.get("source_sha256") or "")):
        raise ValueError("invalid preselection source SHA")
    if "source_artifact_sha256" in payload and not _SHA256.fullmatch(
        str(payload.get("source_artifact_sha256") or "")
    ):
        raise ValueError("invalid preselection source artifact SHA")
    if "source_row_count" in payload:
        value = payload["source_row_count"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("invalid preselection source row count")
    if "source_run_id" in payload and not str(payload.get("source_run_id") or "").strip():
        raise ValueError("invalid preselection source run id")
    for field in ("signal_date", "target_date"):
        if field in payload:
            value = str(payload.get(field) or "")
            if _date(value) != value:
                raise ValueError(f"invalid preselection {field}")
    if "target_date" in payload and payload["target_date"] != payload["trade_date"]:
        raise ValueError("preselection target date mismatch")
    if "stage_selection_eligible" in payload and not isinstance(
        payload["stage_selection_eligible"], bool
    ):
        raise ValueError("invalid preselection stage selection flag")
    if any(payload.get(field) is not False for field in ("production_allowed", "buy_gate_updated", "orders_sent")):
        raise ValueError("unsafe preselection-pool artifact")
    rows = payload.get("rows")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ValueError("invalid preselection-pool rows")
    if not isinstance(payload.get("cannot_confirm"), list):
        raise ValueError("invalid preselection-pool cannot_confirm")
    if not rows and payload.get("status") not in {"CANNOT_CONFIRM", "MISSING", "VALID_EMPTY"}:
        raise ValueError("empty pool requires an explicit status")
    _assert_safe(payload)
    return trade_date


def _legacy_research_flag_view(value: Any, *, depth: int = 0) -> Any:
    """Declared legacy shape: the HK 0.2 lane serialized ``research_only``
    as the string ``"True"`` in its pool rows.  Normalize exactly that
    truthy spelling for the guard view only; every other value still fails
    closed in the shared guard, and the persisted artifact is never
    rewritten."""

    if depth > 128:
        raise ValueError("preselection-pool payload nesting")
    if isinstance(value, Mapping):
        view: dict[Any, Any] = {}
        for key, nested in value.items():
            if (
                isinstance(key, str)
                and key.casefold() == "research_only"
                and isinstance(nested, str)
                and nested.strip().lower() == "true"
            ):
                view[key] = True
            else:
                view[key] = _legacy_research_flag_view(nested, depth=depth + 1)
        return view
    if isinstance(value, list):
        return [_legacy_research_flag_view(item, depth=depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(_legacy_research_flag_view(item, depth=depth + 1) for item in value)
    return value


def _assert_safe(value: Any) -> None:
    assert_safe_tree(_legacy_research_flag_view(value), label="preselection-pool")
