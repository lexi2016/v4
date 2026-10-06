"""Isolated contract tests for the strict V4 stage-acquisition seam.

The fixtures are created below the repository root and are deleted by each
test.  They contain no market data and never use the formal runtime root.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping
from unittest import mock

import infrastructure.stage_acquisition_universe_commit as commit_module
from infrastructure.data_store import _canonical_bytes, _sha256
from infrastructure.interprocess_lock import owned_interprocess_lock
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.secure_evidence_fs import SecureEvidenceError, SecureEvidenceRoot
from infrastructure.stage_acquisition_universe_commit import (
    STRICT_ROLE,
    StageAcquisitionUniverseCommit,
    StrictCommitError,
)
from infrastructure.stage_acquisition_universe_contracts import (
    StageAcquisitionContractError,
    read_strict_a_preselection_snapshot,
)
from ops.materialize_stage_acquisition_universe import (
    build_artifact,
    materialize_stage_acquisition_universe,
)
from ops.run_v35_macos_scheduler import ensure_stage_candidate_input
from stage_center.candidate_input import (
    CandidateInputError,
    ROLE as LEGACY_ROLE,
    read_candidate_input,
)
from stage_center.input_contracts import REQUIRED_A_STAGE_POOL_IDS, a_pool_contract


REPO_ROOT = Path(__file__).resolve().parents[1]
TRADE_DATE = "20260911"
LEGACY_DATE = "20260730"
RELEASE_ID = "fixture-v16"

_SUCCESSOR_SYMBOLS = {
    REQUIRED_A_STAGE_POOL_IDS[0]: ["A.000001"],
    REQUIRED_A_STAGE_POOL_IDS[1]: ["A.000002"],
    REQUIRED_A_STAGE_POOL_IDS[2]: ["A.000003"],
    # The later pools repeat these codes so an append to this pool is an
    # actual suffix extension of the aggregate union.
    REQUIRED_A_STAGE_POOL_IDS[3]: ["A.000004", "A.000005", "A.000006"],
    REQUIRED_A_STAGE_POOL_IDS[4]: ["A.000005"],
    REQUIRED_A_STAGE_POOL_IDS[5]: ["A.000006"],
}


def _source_sha(pool_id: str, trade_date: str) -> str:
    return hashlib.sha256(f"fixture:{pool_id}:{trade_date}".encode()).hexdigest()


def _pool_payload(
    pool_id: str,
    trade_date: str,
    symbols: list[str],
    *,
    row_updates: Mapping[str, Any] | None = None,
    payload_updates: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    status, producer, source_role = a_pool_contract(pool_id)
    rows = []
    for symbol in symbols:
        row: dict[str, Any] = {
            "pool_id": pool_id,
            "symbol": symbol,
            "market": "A",
        }
        if row_updates:
            row.update(row_updates)
        rows.append(row)
    payload: dict[str, Any] = {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": trade_date,
        "pool_id": pool_id,
        "display_name": pool_id,
        "market": "A",
        "status": status,
        "producer_id": producer,
        "source_role": source_role,
        "source_path": f"fixture/{pool_id}.json",
        "source_sha256": _source_sha(pool_id, trade_date),
        "rows": rows,
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if payload_updates:
        payload.update(payload_updates)
    return payload


def _write_pool_set(
    root: Path,
    trade_date: str = TRADE_DATE,
    *,
    symbols_by_pool: Mapping[str, list[str]] | None = None,
    pool_updates: Mapping[str, Mapping[str, Any]] | None = None,
    row_updates: Mapping[str, Mapping[str, Any]] | None = None,
    pool_ids: tuple[str, ...] = REQUIRED_A_STAGE_POOL_IDS,
) -> None:
    symbols_by_pool = symbols_by_pool or _SUCCESSOR_SYMBOLS
    store = PreselectionPoolStore(root)
    for pool_id in pool_ids:
        store.materialize(
            _pool_payload(
                pool_id,
                trade_date,
                list(symbols_by_pool[pool_id]),
                row_updates=(row_updates or {}).get(pool_id),
                payload_updates=(pool_updates or {}).get(pool_id),
            )
        )


def _rewrite_pool(
    root: Path,
    trade_date: str,
    pool_id: str,
    symbols: list[str],
    *,
    payload_updates: Mapping[str, Any] | None = None,
) -> None:
    """Mutate only an isolated fixture, preserving the physical trio contract."""

    store = PreselectionPoolStore(root)
    artifact_relative, receipt_relative = store._relative(trade_date, pool_id)
    artifact_path = root / artifact_relative
    receipt_path = root / receipt_relative
    manifest_path = root / f"preselection_pools/{trade_date}/manifest.json"
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload["rows"] = [
        {"pool_id": pool_id, "symbol": symbol, "market": "A"}
        for symbol in symbols
    ]
    if payload_updates:
        payload.update(payload_updates)
    digest = _sha256(payload)
    receipt = store._receipt(
        trade_date=trade_date,
        pool_id=pool_id,
        artifact_path=artifact_relative,
        artifact_sha256=digest,
        payload=payload,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[pool_id] = digest
    artifact_path.write_bytes(_canonical_bytes(payload))
    receipt_path.write_bytes(_canonical_bytes(receipt))
    manifest_path.write_bytes(_canonical_bytes(manifest))


def _strict_current_path(root: Path, trade_date: str = TRADE_DATE) -> Path:
    return root / f"current/{trade_date}/{STRICT_ROLE}/current.json"


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(value))


def _write_legacy_v2_fixture(root: Path, trade_date: str = LEGACY_DATE) -> None:
    run_id = "legacy-fixture"
    prefix = f"runs/{trade_date}/{LEGACY_ROLE}/{run_id}/"
    current_relative = f"current/{trade_date}/{LEGACY_ROLE}/current.json"
    codes = ["A.000001"]
    codes_sha = hashlib.sha256(_canonical_bytes(codes)).hexdigest()
    projection_sha = "a" * 64
    artifact: dict[str, Any] = {
        "schema_version": LEGACY_ROLE,
        "artifact_role": LEGACY_ROLE,
        "artifact_version": "V2",
        "status": "READY",
        "trade_date": trade_date,
        "codes": codes,
        "row_count": 1,
        "codes_sha256": codes_sha,
        "source_projection_sha256": projection_sha,
        "source_projection_row_count": 1,
        "source_merge_role": "STAGE_ACQUISITION_INPUT",
        "stage_selection_eligible": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    artifact_relative = prefix + "artifact.json"
    manifest_relative = prefix + "manifest.json"
    receipt_relative = prefix + "receipt.json"
    artifact_sha = hashlib.sha256(_canonical_bytes(artifact)).hexdigest()
    manifest: dict[str, Any] = {
        "schema_version": "v3_5.stage_acquisition_universe.manifest.v2",
        "trade_date": trade_date,
        "role": LEGACY_ROLE,
        "run_id": run_id,
        "status": "READY",
        "row_count": 1,
        "codes_sha256": codes_sha,
        "source_projection_sha256": projection_sha,
        "artifact_sha256": artifact_sha,
        "artifact_relative": artifact_relative,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    manifest_sha = hashlib.sha256(_canonical_bytes(manifest)).hexdigest()
    receipt: dict[str, Any] = {
        "schema_version": "v3_5.stage_acquisition_universe.receipt.v2",
        "trade_date": trade_date,
        "role": LEGACY_ROLE,
        "run_id": run_id,
        "status": "READY",
        "row_count": 1,
        "codes_sha256": codes_sha,
        "source_projection_sha256": projection_sha,
        "artifact_sha256": artifact_sha,
        "manifest_sha256": manifest_sha,
        "artifact_relative": artifact_relative,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    receipt_sha = hashlib.sha256(_canonical_bytes(receipt)).hexdigest()
    current: dict[str, Any] = {
        "schema_version": "v3_5.stage_acquisition_universe.current.v2",
        "trade_date": trade_date,
        "role": LEGACY_ROLE,
        "run_id": run_id,
        "status": "READY",
        "row_count": 1,
        "codes_sha256": codes_sha,
        "source_projection_sha256": projection_sha,
        "artifact_sha256": artifact_sha,
        "manifest_sha256": manifest_sha,
        "receipt_sha256": receipt_sha,
        "artifact_relative": artifact_relative,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    _write_json(root / artifact_relative, artifact)
    _write_json(root / manifest_relative, manifest)
    _write_json(root / receipt_relative, receipt)
    _write_json(root / current_relative, current)


class StrictStageAcquisitionV4Tests(unittest.TestCase):
    def fixture_root(self):
        return tempfile.TemporaryDirectory(dir=str(REPO_ROOT), prefix=".strict-acquisition-test-")

    def test_complete_physical_chain_and_strict_readback(self) -> None:
        with self.fixture_root() as temporary:
            root = Path(temporary)
            _write_pool_set(root)
            with mock.patch.dict(os.environ, {"V35_RELEASE_ID": RELEASE_ID}, clear=False):
                scheduled = ensure_stage_candidate_input(
                    data_root=root,
                    business_date=TRADE_DATE,
                )
            self.assertEqual(scheduled["status"], "READY")
            self.assertEqual(scheduled["row_count"], 6)
            chain = StageAcquisitionUniverseCommit(root).read_current(TRADE_DATE)
            artifact = chain["artifact"]
            self.assertEqual(artifact["artifact_role"], STRICT_ROLE)
            self.assertEqual(
                len(artifact["source_pool_provenance"]),
                len(REQUIRED_A_STAGE_POOL_IDS),
            )
            for item in artifact["source_pool_provenance"]:
                for field in (
                    "pool_sha256",
                    "artifact_raw_sha256",
                    "manifest_raw_sha256",
                    "receipt_raw_sha256",
                ):
                    self.assertRegex(item[field], r"^[0-9a-f]{64}$")
            current = _strict_current_path(root).read_bytes()
            self.assertEqual(hashlib.sha256(current).hexdigest(), chain["current_bytes_sha256"])
            candidate = read_candidate_input(root, TRADE_DATE)
            self.assertEqual(
                candidate.codes,
                ("A.000001", "A.000002", "A.000003", "A.000004", "A.000005", "A.000006"),
            )
            self.assertEqual(candidate.strict_schema, "v3")
            self.assertEqual(candidate.digest_mode, "RAW_BYTES_V1")
            self.assertEqual(len(candidate.source_evidence), 5)

    def test_pool_snapshot_rejects_replaced_physical_root(self) -> None:
        with self.fixture_root() as temporary:
            fixture = Path(temporary)
            root = fixture / "data"
            root.mkdir()
            _write_pool_set(root)
            store = PreselectionPoolStore(root)
            old_root = fixture / "old-data"
            os.replace(root, old_root)
            root.mkdir()
            changed = dict(_SUCCESSOR_SYMBOLS)
            changed[REQUIRED_A_STAGE_POOL_IDS[0]] = ["A.000009"]
            _write_pool_set(root, symbols_by_pool=changed)

            with self.assertRaises(ValueError) as context:
                store.read_pool_snapshot(
                    TRADE_DATE, REQUIRED_A_STAGE_POOL_IDS[0]
                )
            self.assertIn("OWNED_ROOT_REPLACED", str(context.exception))

    def test_pool_snapshot_rejects_invalid_and_expired_lock_leases(self) -> None:
        with self.fixture_root() as temporary:
            root = Path(temporary)
            store = PreselectionPoolStore(root)
            lock_path = root / ".import.lock"

            with self.assertRaisesRegex(ValueError, "OWNER_LOCK_LEASE_NOT_OWNED"):
                store.read_pool_snapshot(
                    TRADE_DATE,
                    REQUIRED_A_STAGE_POOL_IDS[0],
                    lock_lease=True,
                )
            self.assertFalse(lock_path.exists())
            self.assertFalse(Path(f"{lock_path}.mutex").exists())

            with owned_interprocess_lock(
                lock_path,
                timeout_seconds=1,
                timeout_message="fixture lock timeout",
            ) as lease:
                expired_lease = lease

            with self.assertRaisesRegex(ValueError, "OWNER_LOCK_LEASE_NOT_ACTIVE"):
                store.read_pool_snapshot(
                    TRADE_DATE,
                    REQUIRED_A_STAGE_POOL_IDS[0],
                    lock_lease=expired_lease,
                )

    def test_pool_snapshot_rejects_wrong_root_and_non_holder_lock_leases(self) -> None:
        with self.fixture_root() as temporary:
            root = Path(temporary)
            other_root = root / "other"
            other_root.mkdir()
            store = PreselectionPoolStore(root)
            other_store = PreselectionPoolStore(other_root)
            lock_path = root / ".import.lock"

            with owned_interprocess_lock(
                lock_path,
                timeout_seconds=1,
                timeout_message="fixture lock timeout",
            ) as lease:
                with self.assertRaisesRegex(ValueError, "OWNER_LOCK_LEASE_PATH_MISMATCH"):
                    other_store.read_pool_snapshot(
                        TRADE_DATE,
                        REQUIRED_A_STAGE_POOL_IDS[0],
                        lock_lease=lease,
                    )

                with ThreadPoolExecutor(max_workers=1) as executor:
                    result = executor.submit(
                        store.read_pool_snapshot,
                        TRADE_DATE,
                        REQUIRED_A_STAGE_POOL_IDS[0],
                        lock_lease=lease,
                    )
                    with self.assertRaisesRegex(ValueError, "OWNER_LOCK_LEASE_NOT_OWNED"):
                        result.result(timeout=2)

    def test_locked_publication_rejects_manifest_trio_tamper(self) -> None:
        with self.fixture_root() as temporary:
            root = Path(temporary)
            _write_pool_set(root)
            artifact = build_artifact(root, TRADE_DATE)
            pool_id = REQUIRED_A_STAGE_POOL_IDS[0]
            original = commit_module.read_strict_a_preselection_snapshot
            state: dict[str, Any] = {"calls": 0, "snapshots": []}

            def reader_with_manifest_tamper(
                data_root: Path,
                date: str,
                *args: Any,
                **kwargs: Any,
            ) -> Any:
                snapshot = original(data_root, date, *args, **kwargs)
                state["calls"] += 1
                state["snapshots"].append(snapshot)
                if state["calls"] == 1:
                    manifest_path = root / f"preselection_pools/{TRADE_DATE}/manifest.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest[pool_id] = "f" * 64
                    _write_json(manifest_path, manifest)
                return snapshot

            identity = commit_module.EvidenceIdentity(
                owner_id="V3_5_STAGE_CENTER",
                producer_id="ops.materialize_stage_acquisition_universe",
                release_id=RELEASE_ID,
                lane_id="A_SHARE_STAGE_ACQUISITION",
            )
            with mock.patch.object(
                commit_module,
                "read_strict_a_preselection_snapshot",
                side_effect=reader_with_manifest_tamper,
            ):
                with self.assertRaises(StrictCommitError) as context:
                    StageAcquisitionUniverseCommit(root).publish(
                        artifact,
                        run_id="manifest-tamper",
                        identity=identity,
                    )

            self.assertEqual(state["calls"], 2)
            self.assertNotEqual(state["snapshots"][0], state["snapshots"][1])
            self.assertIn(pool_id, state["snapshots"][1].pool_diagnostics)
            self.assertIn("snapshot changed before publication", str(context.exception))
            self.assertFalse(_strict_current_path(root).exists())

    def test_locked_publication_rejects_source_change_after_snapshot(self) -> None:
        with self.fixture_root() as temporary:
            root = Path(temporary)
            _write_pool_set(root)
            artifact = build_artifact(root, TRADE_DATE)
            original = commit_module.read_strict_a_preselection_snapshot
            state = {"calls": 0}

            def reader_with_source_change(
                data_root: Path,
                date: str,
                *args: Any,
                **kwargs: Any,
            ) -> Any:
                snapshot = original(data_root, date, *args, **kwargs)
                state["calls"] += 1
                if state["calls"] == 1:
                    appendable = REQUIRED_A_STAGE_POOL_IDS[3]
                    _rewrite_pool(
                        root,
                        TRADE_DATE,
                        appendable,
                        _SUCCESSOR_SYMBOLS[appendable] + ["A.000007"],
                    )
                return snapshot

            identity = commit_module.EvidenceIdentity(
                owner_id="V3_5_STAGE_CENTER",
                producer_id="ops.materialize_stage_acquisition_universe",
                release_id=RELEASE_ID,
                lane_id="A_SHARE_STAGE_ACQUISITION",
            )
            with mock.patch.object(
                commit_module,
                "read_strict_a_preselection_snapshot",
                side_effect=reader_with_source_change,
            ):
                with self.assertRaises(StrictCommitError) as context:
                    StageAcquisitionUniverseCommit(root).publish(
                        artifact,
                        run_id="source-race",
                        identity=identity,
                    )
            self.assertEqual(state["calls"], 2)
            self.assertIn("snapshot changed before publication", str(context.exception))
            self.assertFalse(_strict_current_path(root).exists())

    def test_locked_successor_rejects_source_change_and_keeps_current(self) -> None:
        with self.fixture_root() as temporary:
            root = Path(temporary)
            _write_pool_set(root)
            first = materialize_stage_acquisition_universe(
                root, TRADE_DATE, release_id=RELEASE_ID, run_id="initial"
            )
            pointer_before = _strict_current_path(root).read_bytes()
            appendable = REQUIRED_A_STAGE_POOL_IDS[3]
            _rewrite_pool(
                root,
                TRADE_DATE,
                appendable,
                _SUCCESSOR_SYMBOLS[appendable] + ["A.000007"],
            )
            artifact = build_artifact(root, TRADE_DATE)
            original = commit_module.read_strict_a_preselection_snapshot
            state = {"calls": 0}

            def reader_with_second_source_change(
                data_root: Path,
                date: str,
                *args: Any,
                **kwargs: Any,
            ) -> Any:
                snapshot = original(data_root, date, *args, **kwargs)
                state["calls"] += 1
                if state["calls"] == 1:
                    _rewrite_pool(
                        root,
                        TRADE_DATE,
                        appendable,
                        _SUCCESSOR_SYMBOLS[appendable]
                        + ["A.000007", "A.000008"],
                    )
                return snapshot

            identity = commit_module.EvidenceIdentity(
                owner_id="V3_5_STAGE_CENTER",
                producer_id="ops.materialize_stage_acquisition_universe",
                release_id=RELEASE_ID,
                lane_id="A_SHARE_STAGE_ACQUISITION",
            )
            with mock.patch.object(
                commit_module,
                "read_strict_a_preselection_snapshot",
                side_effect=reader_with_second_source_change,
            ):
                with self.assertRaises(StrictCommitError) as context:
                    StageAcquisitionUniverseCommit(root).publish_successor(
                        artifact,
                        expected_current_sha256=first["current_bytes_sha256"],
                        reason="source race fixture",
                        run_id="successor-race",
                        identity=identity,
                    )
            self.assertEqual(state["calls"], 2)
            self.assertIn("snapshot changed before publication", str(context.exception))
            self.assertEqual(_strict_current_path(root).read_bytes(), pointer_before)

    def test_missing_wrong_date_identity_and_duplicate_are_scoped(self) -> None:
        with self.fixture_root() as temporary:
            root = Path(temporary)
            _write_pool_set(root, pool_ids=REQUIRED_A_STAGE_POOL_IDS[:-1])
            result = materialize_stage_acquisition_universe(
                root, TRADE_DATE, release_id=RELEASE_ID
            )
            self.assertEqual(result["status"], "READY")
            self.assertEqual(result["row_count"], 6)
            artifact = StageAcquisitionUniverseCommit(root).read_current(TRADE_DATE)[
                "artifact"
            ]
            self.assertFalse(artifact["source_pool_provenance"][-1]["available"])
            self.assertIn(
                f"{REQUIRED_A_STAGE_POOL_IDS[-1]}:",
                " ".join(artifact["cannot_confirm"]),
            )

        with self.fixture_root() as temporary:
            root = Path(temporary)
            _write_pool_set(root, trade_date="20260910")
            with self.assertRaises(StageAcquisitionContractError):
                materialize_stage_acquisition_universe(root, TRADE_DATE, release_id=RELEASE_ID)
            self.assertFalse(_strict_current_path(root).exists())

        with self.fixture_root() as temporary:
            root = Path(temporary)
            _write_pool_set(
                root,
                pool_updates={
                    REQUIRED_A_STAGE_POOL_IDS[1]: {"source_role": "RAW_SOURCE"}
                },
            )
            result = materialize_stage_acquisition_universe(
                root, TRADE_DATE, release_id=RELEASE_ID
            )
            self.assertEqual(result["status"], "READY")
            self.assertEqual(result["row_count"], 5)
            self.assertNotIn("A.000002", result["artifact"]["codes"])
            self.assertTrue(
                any(
                    REQUIRED_A_STAGE_POOL_IDS[1] in reason
                    for reason in result["artifact"]["cannot_confirm"]
                )
            )

        with self.fixture_root() as temporary:
            root = Path(temporary)
            duplicate_pool = REQUIRED_A_STAGE_POOL_IDS[0]
            symbols = dict(_SUCCESSOR_SYMBOLS)
            symbols[duplicate_pool] = ["A.000001", "A.000001"]
            _write_pool_set(root, symbols_by_pool=symbols)
            result = materialize_stage_acquisition_universe(
                root, TRADE_DATE, release_id=RELEASE_ID
            )
            self.assertEqual(result["status"], "READY")
            self.assertEqual(result["row_count"], 5)
            self.assertNotIn("A.000001", result["artifact"]["codes"])
            self.assertTrue(
                any(
                    "duplicate code" in reason
                    for reason in result["artifact"]["cannot_confirm"]
                )
            )

    def test_noncontributing_nonempty_diagnostic_lane_isolated_at_publish(self) -> None:
        with self.fixture_root() as temporary:
            root = Path(temporary)
            good_pool = REQUIRED_A_STAGE_POOL_IDS[0]
            bad_pool = REQUIRED_A_STAGE_POOL_IDS[1]
            _write_pool_set(
                root,
                pool_ids=(good_pool, bad_pool),
                pool_updates={
                    bad_pool: {
                        "status": "available",
                        "producer_id": "v3_fupan_watchlist_upstream_v1",
                        "source_role": "UPSTREAM_PRODUCER_ARTIFACT",
                    }
                },
            )

            result = materialize_stage_acquisition_universe(
                root, TRADE_DATE, release_id=RELEASE_ID
            )
            self.assertEqual(result["status"], "READY")
            self.assertEqual(result["row_count"], 1)
            self.assertEqual(result["artifact"]["codes"], ["A.000001"])
            bad_provenance = next(
                item
                for item in result["artifact"]["source_pool_provenance"]
                if item["pool_id"] == bad_pool
            )
            self.assertTrue(bad_provenance["available"])
            self.assertEqual(bad_provenance["status"], "CANNOT_CONFIRM")
            self.assertEqual(bad_provenance["row_count"], 0)
            self.assertTrue(bad_provenance["valid_empty"])
            for field in (
                "pool_sha256",
                "artifact_raw_sha256",
                "manifest_raw_sha256",
                "receipt_raw_sha256",
            ):
                self.assertRegex(bad_provenance[field], r"^[0-9a-f]{64}$")
            self.assertEqual(
                bad_provenance["producer_id"],
                "v3_fupan_watchlist_upstream_v1",
            )
            self.assertEqual(
                bad_provenance["source_role"],
                "UPSTREAM_PRODUCER_ARTIFACT",
            )
            self.assertIn(
                "SOURCE_STATUS_REJECTED:available",
                " ".join(bad_provenance["diagnostics"]),
            )
            stored_bad_pool = PreselectionPoolStore(root).read_pool_snapshot(
                TRADE_DATE, bad_pool
            )["artifact"]
            self.assertEqual(len(stored_bad_pool["rows"]), 1)
            self.assertEqual(stored_bad_pool["rows"][0]["symbol"], "A.000002")
            self.assertNotIn("A.000002", result["artifact"]["codes"])
            self.assertTrue(_strict_current_path(root).exists())
            candidate = read_candidate_input(root, TRADE_DATE)
            self.assertEqual(candidate.codes, ("A.000001",))

    def test_physical_bytes_future_date_and_safety_fail_without_current(self) -> None:
        with self.fixture_root() as temporary:
            root = Path(temporary)
            _write_pool_set(
                root,
                pool_updates={
                    REQUIRED_A_STAGE_POOL_IDS[0]: {"signal_date": "20260912"}
                },
            )
            result = materialize_stage_acquisition_universe(
                root, TRADE_DATE, release_id=RELEASE_ID
            )
            self.assertEqual(result["status"], "READY")
            self.assertEqual(result["row_count"], 5)
            self.assertTrue(
                any(
                    REQUIRED_A_STAGE_POOL_IDS[0] in reason
                    for reason in result["artifact"]["cannot_confirm"]
                )
            )

        with self.fixture_root() as temporary:
            root = Path(temporary)
            _write_pool_set(root)
            artifact_path = root / (
                f"preselection_pools/{TRADE_DATE}/{REQUIRED_A_STAGE_POOL_IDS[0]}.json"
            )
            artifact_path.write_bytes(artifact_path.read_bytes() + b"\n")
            result = materialize_stage_acquisition_universe(
                root, TRADE_DATE, release_id=RELEASE_ID
            )
            self.assertEqual(result["status"], "READY")
            self.assertEqual(result["row_count"], 5)
            self.assertTrue(
                any(
                    REQUIRED_A_STAGE_POOL_IDS[0] in reason
                    for reason in result["artifact"]["cannot_confirm"]
                )
            )

        with self.fixture_root() as temporary:
            root = Path(temporary)
            _write_pool_set(root)
            _rewrite_pool(
                root,
                TRADE_DATE,
                REQUIRED_A_STAGE_POOL_IDS[0],
                _SUCCESSOR_SYMBOLS[REQUIRED_A_STAGE_POOL_IDS[0]],
                payload_updates={"production_allowed": True},
            )
            result = materialize_stage_acquisition_universe(
                root, TRADE_DATE, release_id=RELEASE_ID
            )
            self.assertEqual(result["status"], "READY")
            self.assertEqual(result["row_count"], 5)
            self.assertTrue(
                any(
                    REQUIRED_A_STAGE_POOL_IDS[0] in reason
                    for reason in result["artifact"]["cannot_confirm"]
                )
            )

    def test_partial_policy_diagnostics_and_full_aggregate_are_preserved(self) -> None:
        with self.fixture_root() as temporary:
            root = Path(temporary)
            _write_pool_set(
                root,
                pool_updates={
                    REQUIRED_A_STAGE_POOL_IDS[0]: {
                        "cannot_confirm": [
                            "RESEARCH_ONLY_NO_BUY_GATE",
                            "RANK_FOR_REVIEW_ONLY_NOT_BUY_PRIORITY",
                        ]
                    }
                },
            )
            snapshot = read_strict_a_preselection_snapshot(root, TRADE_DATE)
            self.assertTrue(snapshot.ready)
            self.assertIn("RESEARCH_ONLY_NO_BUY_GATE", snapshot.policy_notes)
            self.assertIn(
                "RANK_FOR_REVIEW_ONLY_NOT_BUY_PRIORITY", snapshot.policy_notes
            )
            self.assertEqual(snapshot.row_count, 6)

    def test_nonempty_subset_and_large_pool_are_not_truncated(self) -> None:
        with self.fixture_root() as temporary:
            root = Path(temporary)
            large = [f"A.{index:06d}" for index in range(1, 206)]
            symbols = dict(_SUCCESSOR_SYMBOLS)
            symbols[REQUIRED_A_STAGE_POOL_IDS[0]] = large
            _write_pool_set(
                root,
                symbols_by_pool=symbols,
                pool_ids=(REQUIRED_A_STAGE_POOL_IDS[0],),
            )
            result = materialize_stage_acquisition_universe(
                root, TRADE_DATE, release_id=RELEASE_ID
            )
            self.assertEqual(result["status"], "READY")
            self.assertEqual(result["row_count"], 205)
            self.assertEqual(len(result["artifact"]["codes"]), 205)
            self.assertEqual(result["artifact"]["codes"][-1], "A.000205")

    def test_all_empty_known_lanes_remain_cannot_confirm(self) -> None:
        with self.fixture_root() as temporary:
            root = Path(temporary)
            updates = {
                pool_id: {
                    "status": "CANNOT_CONFIRM",
                    "source_role": "EXPECTED_MISSING",
                    "rows": [],
                    "cannot_confirm": ["MISSING"],
                }
                for pool_id in REQUIRED_A_STAGE_POOL_IDS
            }
            _write_pool_set(root, pool_updates=updates)
            snapshot = read_strict_a_preselection_snapshot(root, TRADE_DATE)
            self.assertFalse(snapshot.ready)
            self.assertEqual(snapshot.status, "CANNOT_CONFIRM")
            self.assertEqual(snapshot.row_count, 0)
            with self.assertRaises(StageAcquisitionContractError):
                materialize_stage_acquisition_universe(
                    root, TRADE_DATE, release_id=RELEASE_ID
                )
            self.assertFalse(_strict_current_path(root).exists())

    def test_same_day_successor_cas_is_append_only_and_stale_cas_is_rejected(self) -> None:
        with self.fixture_root() as temporary:
            root = Path(temporary)
            _write_pool_set(root)
            first = materialize_stage_acquisition_universe(
                root, TRADE_DATE, release_id=RELEASE_ID, run_id="initial"
            )
            previous_pointer = _strict_current_path(root).read_bytes()
            appendable = REQUIRED_A_STAGE_POOL_IDS[3]
            _rewrite_pool(
                root,
                TRADE_DATE,
                appendable,
                _SUCCESSOR_SYMBOLS[appendable] + ["A.000007"],
            )
            successor = materialize_stage_acquisition_universe(
                root,
                TRADE_DATE,
                release_id=RELEASE_ID,
                run_id="successor",
                expected_current_sha256=first["current_bytes_sha256"],
                successor_reason="fixture append",
            )
            self.assertEqual(successor["status"], "SUPERSEDED")
            self.assertEqual(successor["current_status"], "READY")
            self.assertEqual(successor["row_count"], 7)
            self.assertNotEqual(_strict_current_path(root).read_bytes(), previous_pointer)
            candidate = read_candidate_input(root, TRADE_DATE)
            self.assertEqual(candidate.codes[-1], "A.000007")

            current_after_successor = _strict_current_path(root).read_bytes()
            with self.assertRaises(StrictCommitError):
                materialize_stage_acquisition_universe(
                    root,
                    TRADE_DATE,
                    release_id=RELEASE_ID,
                    run_id="stale-cas",
                    expected_current_sha256=first["current_bytes_sha256"],
                    successor_reason="stale fixture token",
                )
            self.assertEqual(_strict_current_path(root).read_bytes(), current_after_successor)

    def test_secure_path_boundary_and_cross_process_lock(self) -> None:
        with self.fixture_root() as temporary:
            root = Path(temporary)
            outside = root / "outside.txt"
            outside.write_bytes(b"outside")
            link = root / "link.txt"
            link.symlink_to(outside)
            with SecureEvidenceRoot(root, max_file_bytes=1024) as secure:
                with self.assertRaises(SecureEvidenceError):
                    secure.read_regular_bytes("../outside.txt")
                with self.assertRaises(SecureEvidenceError):
                    secure.read_regular_bytes("link.txt")

            with owned_interprocess_lock(
                root / ".import.lock",
                timeout_seconds=1.0,
                timeout_message="fixture parent lock timeout",
            ):
                child_code = (
                    "from pathlib import Path\n"
                    "from infrastructure.interprocess_lock import owned_interprocess_lock\n"
                    f"root=Path({json.dumps(str(root))})\n"
                    "try:\n"
                    "    with owned_interprocess_lock(root/'.import.lock', timeout_seconds=0.1, "
                    "timeout_message='fixture child lock timeout', poll_seconds=0.01):\n"
                    "        raise SystemExit(2)\n"
                    "except ValueError:\n"
                    "    print('LOCKED')\n"
                )
                completed = subprocess.run(
                    [os.fspath(Path(os.sys.executable)), "-c", child_code],
                    cwd=REPO_ROOT,
                    env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(completed.stdout.strip(), "LOCKED")

    def test_legacy_v2_requires_explicit_mode(self) -> None:
        with self.fixture_root() as temporary:
            root = Path(temporary)
            _write_legacy_v2_fixture(root)
            with self.assertRaises(CandidateInputError):
                read_candidate_input(root, LEGACY_DATE)
            candidate = read_candidate_input(
                root, LEGACY_DATE, compatibility_mode="LEGACY_V2"
            )
            self.assertEqual(candidate.codes, ("A.000001",))
            self.assertIsNone(candidate.commit_id)
            with self.assertRaises(CandidateInputError):
                read_candidate_input(root, LEGACY_DATE, compatibility_mode="UNKNOWN")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
