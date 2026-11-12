from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from infrastructure.stage_acquisition_universe_commit import (
    DIGEST_MODE,
    EvidenceIdentity,
    StageAcquisitionUniverseCommit,
    STRICT_ARTIFACT_SCHEMA,
    STRICT_ROLE,
    StrictCommitError,
)
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.secure_evidence_fs import SecureEvidenceRoot
from infrastructure.stage_acquisition_universe_contracts import (
    build_strict_stage_acquisition_universe,
    read_strict_a_preselection_snapshot,
)
from infrastructure.stage_acquisition_universe_store import StageAcquisitionUniverseStore
from stage_center.input_contracts import REQUIRED_A_STAGE_POOL_IDS, a_pool_contract
from stage_center.candidate_input import CandidateInputError, read_candidate_input


TRADE_DATE = "20260902"
IDENTITY = EvidenceIdentity(
    owner_id="V3_5_STAGE_CENTER",
    producer_id="ops.materialize_stage_acquisition_universe",
    release_id="release-test-1",
    lane_id="A_SHARE_STAGE_ACQUISITION",
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _artifact(*codes: str) -> dict[str, object]:
    provenance = []
    for index, pool_id in enumerate(REQUIRED_A_STAGE_POOL_IDS):
        provenance.append(
            {
                "pool_id": pool_id,
                "status": "READY",
                "producer_id": f"producer-{index}",
                "source_role": f"SOURCE_ROLE_{index}",
                "row_count": 1,
                "valid_empty": False,
                "artifact_relative_path": f"preselection_pools/{TRADE_DATE}/{pool_id}.json",
                "manifest_relative_path": f"preselection_pools/{TRADE_DATE}/manifest.json",
                "receipt_relative_path": f"preselection_pools/{TRADE_DATE}/receipts/{pool_id}.json",
                "pool_sha256": hashlib.sha256(pool_id.encode()).hexdigest(),
                "artifact_raw_sha256": hashlib.sha256(f"{pool_id}-artifact".encode()).hexdigest(),
                "manifest_raw_sha256": hashlib.sha256(f"{pool_id}-manifest".encode()).hexdigest(),
                "receipt_raw_sha256": hashlib.sha256(f"{pool_id}-receipt".encode()).hexdigest(),
            }
        )
    return {
        "schema_version": STRICT_ARTIFACT_SCHEMA,
        "artifact_role": STRICT_ROLE,
        "artifact_version": "V3",
        "authority": "STRICT_PHYSICAL_POOL_SNAPSHOT",
        "status": "READY",
        "trade_date": TRADE_DATE,
        "codes": list(codes),
        "row_count": len(codes),
        "codes_sha256": hashlib.sha256(_canonical_bytes(list(codes))).hexdigest(),
        "source_projection_sha256": hashlib.sha256(b"projection").hexdigest(),
        "source_projection_row_count": len(codes),
        "source_projection_status": "READY_WITH_ROWS",
        "source_pool_provenance": provenance,
        "source_pool_provenance_sha256": hashlib.sha256(_canonical_bytes(provenance)).hexdigest(),
        "code_sources": {code: [REQUIRED_A_STAGE_POOL_IDS[0]] for code in codes},
        "source_merge_role": "STAGE_ACQUISITION_INPUT",
        "stage_selection_eligible": True,
        "policy_notes": [],
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _physical_payload(root: Path, *codes: str) -> dict[str, object]:
    pool_store = PreselectionPoolStore(root)
    for index, pool_id in enumerate(REQUIRED_A_STAGE_POOL_IDS):
        status, producer_id, source_role = a_pool_contract(pool_id)
        pool_codes = codes if index == 0 else codes[:1]
        source_path = f"fixture://{TRADE_DATE}/{pool_id}"
        pool_store.materialize(
            {
                "schema_version": "v3_5.preselection_pool.v1",
                "trade_date": TRADE_DATE,
                "pool_id": pool_id,
                "display_name": pool_id,
                "market": "A",
                "status": status,
                "producer_id": producer_id,
                "source_role": source_role,
                "source_path": source_path,
                "source_sha256": hashlib.sha256(source_path.encode()).hexdigest(),
                "rows": [
                    {
                        "market": "A",
                        "symbol": code,
                        "pool_id": pool_id,
                        "recommendation_status": "WATCH_ONLY",
                    }
                    for code in pool_codes
                ],
                "cannot_confirm": [],
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
    snapshot = read_strict_a_preselection_snapshot(root, TRADE_DATE)
    return build_strict_stage_acquisition_universe(snapshot)


def _publish(store: StageAcquisitionUniverseStore, *codes: str, run_id: str = "run-1"):
    payload = _physical_payload(store.root, *codes)
    return store.publish(payload, run_id=run_id, identity=IDENTITY)


def _paths(store: StageAcquisitionUniverseStore) -> dict[str, Path]:
    result = store.read_strict_verified(TRADE_DATE)
    return {
        "artifact": Path(result["artifact_path"]),
        "manifest": Path(result["manifest_path"]),
        "receipt": Path(result["receipt_path"]),
        "commit": Path(result["commit_marker_path"]),
        "current": Path(result["current_path"]),
    }


def _write_json_bytes(path: Path, value: object) -> None:
    path.write_bytes(_canonical_bytes(value))


def _mutated_bytes(raw: bytes, kind: str) -> bytes:
    if kind == "whitespace":
        return raw + b" "
    if kind == "key_order":
        value = json.loads(raw.decode("utf-8"))
        return json.dumps(
            dict(reversed(list(value.items()))), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    if kind == "bom":
        return b"\xef\xbb\xbf" + raw
    if kind == "newline":
        return raw + b"\n"
    if kind == "garbage":
        return raw + b"garbage"
    if kind == "truncation":
        return raw[:-1]
    if kind == "single_byte":
        index = max(1, len(raw) // 2)
        return raw[:index] + bytes((raw[index] ^ 1,)) + raw[index + 1 :]
    raise AssertionError(kind)


def test_strict_publish_requires_identity_and_release_before_writes(tmp_path: Path) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    with pytest.raises(ValueError, match="identity"):
        store.publish(_artifact("A.000001"), run_id="missing-identity")
    assert not (tmp_path / "runs").exists()


def test_strict_chain_publishes_raw_and_canonical_bindings(tmp_path: Path) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    result = _publish(store, "A.000001", "A.000002")
    assert result["status"] == "READY"
    assert result["digest_mode"] == DIGEST_MODE
    assert result["artifact_bytes_sha256"] == result["artifact_canonical_sha256"]
    candidate = read_candidate_input(tmp_path, TRADE_DATE)
    assert candidate.digest_mode == DIGEST_MODE
    assert candidate.strict_schema == "v3"
    assert candidate.codes == ("A.000001", "A.000002")


@pytest.mark.parametrize("component", ("artifact", "manifest", "receipt", "commit", "current"))
def test_strict_reader_rejects_any_component_byte_mutation(tmp_path: Path, component: str) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    _publish(store, "A.000001")
    result = store.read_strict_verified(TRADE_DATE)
    paths = {
        "artifact": result["artifact_path"],
        "manifest": result["manifest_path"],
        "receipt": result["receipt_path"],
        "commit": result["commit_marker_path"],
        "current": result["current_path"],
    }
    path = Path(paths[component])
    raw = path.read_bytes()
    path.write_bytes(raw + (b" " if component != "current" else b"\n"))
    with pytest.raises((CandidateInputError, ValueError)):
        read_candidate_input(tmp_path, TRADE_DATE)


@pytest.mark.parametrize(
    "component",
    ("artifact", "manifest", "receipt", "commit", "current"),
)
@pytest.mark.parametrize(
    "kind",
    ("whitespace", "key_order", "bom", "newline", "garbage", "truncation", "single_byte"),
)
def test_strict_reader_rejects_raw_and_noncanonical_mutations(
    tmp_path: Path, component: str, kind: str
) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    _publish(store, "A.000001")
    path = _paths(store)[component]
    mutated = _mutated_bytes(path.read_bytes(), kind)
    path.write_bytes(mutated)
    with pytest.raises(CandidateInputError):
        read_candidate_input(tmp_path, TRADE_DATE)
    assert path.read_bytes() == mutated


@pytest.mark.parametrize("component", ("artifact", "manifest", "receipt", "commit", "current"))
@pytest.mark.parametrize("field", ("owner_id", "producer_id", "release_id", "lane_id", "trade_date"))
def test_strict_reader_rejects_identity_or_date_mutation(
    tmp_path: Path, component: str, field: str
) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    _publish(store, "A.000001")
    path = _paths(store)[component]
    value = json.loads(path.read_text(encoding="utf-8"))
    if field == "owner_id":
        value[field] = "OTHER_OWNER"
    elif field == "producer_id":
        value[field] = "OTHER_PRODUCER"
    elif field == "release_id":
        value[field] = "other-release"
    elif field == "lane_id":
        value[field] = "OTHER_LANE"
    else:
        value[field] = "20260903"
    _write_json_bytes(path, value)
    with pytest.raises(CandidateInputError):
        read_candidate_input(tmp_path, TRADE_DATE)


@pytest.mark.parametrize("component", ("artifact", "manifest", "receipt", "commit", "current"))
@pytest.mark.parametrize("field", ("production_allowed", "buy_gate_updated", "orders_sent"))
def test_strict_reader_rejects_safety_mutation(
    tmp_path: Path, component: str, field: str
) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    _publish(store, "A.000001")
    path = _paths(store)[component]
    value = json.loads(path.read_text(encoding="utf-8"))
    value[field] = True
    _write_json_bytes(path, value)
    with pytest.raises(CandidateInputError):
        read_candidate_input(tmp_path, TRADE_DATE)


@pytest.mark.parametrize("field", ("commit_id", "commit_marker_relative", "commit_marker_bytes_sha256", "commit_marker_canonical_sha256"))
def test_strict_reader_rejects_missing_current_marker_field(tmp_path: Path, field: str) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    _publish(store, "A.000001")
    path = _paths(store)["current"]
    value = json.loads(path.read_text(encoding="utf-8"))
    value.pop(field)
    _write_json_bytes(path, value)
    with pytest.raises(CandidateInputError):
        read_candidate_input(tmp_path, TRADE_DATE)


def test_strict_reader_rejects_missing_marker_even_when_current_exists(tmp_path: Path) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    _publish(store, "A.000001")
    result = store.read_strict_verified(TRADE_DATE)
    Path(result["commit_marker_path"]).unlink()
    with pytest.raises(CandidateInputError, match="marker"):
        read_candidate_input(tmp_path, TRADE_DATE)


def test_legacy_current_requires_explicit_legacy_reader(tmp_path: Path) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    with pytest.raises(ValueError):
        store.publish(_artifact("A.000001"), run_id="legacy")


def test_strict_current_is_not_read_by_legacy_reader(tmp_path: Path) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    _publish(store, "A.000001")
    with pytest.raises(CandidateInputError):
        read_candidate_input(tmp_path, TRADE_DATE, compatibility_mode="LEGACY_V2")


@pytest.mark.parametrize("component", ("artifact", "manifest", "receipt", "commit", "current"))
def test_rejected_current_never_overwrites_existing_evidence(
    tmp_path: Path, component: str
) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    _publish(store, "A.000001")
    paths = _paths(store)
    target = paths[component]
    raw = target.read_bytes()
    target.write_bytes(_mutated_bytes(raw, "single_byte"))
    before = {name: path.read_bytes() for name, path in paths.items()}
    with pytest.raises(StrictCommitError):
        store.publish(_artifact("A.000002"), run_id="rejected", identity=IDENTITY)
    assert {name: path.read_bytes() for name, path in paths.items()} == before
    assert not (tmp_path / "runs" / TRADE_DATE / STRICT_ROLE / "rejected").exists()


@pytest.mark.parametrize("point", range(1, 9))
def test_strict_publish_recovers_each_crash_boundary(
    tmp_path: Path, point: int, monkeypatch
) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    payload = _physical_payload(store.root, "A.000001")
    run_id = f"crash-{point}"
    fired = False

    if point in {1, 2, 3, 4}:
        original_create = SecureEvidenceRoot.create_immutable_bytes
        suffix = {
            1: "/artifact.json",
            2: "/manifest.json",
            3: "/receipt.json",
            4: "/commit.json",
        }[point]

        def fail_after_immutable_write(self, relative: str, data: bytes) -> str:
            nonlocal fired
            result = original_create(self, relative, data)
            if not fired and relative.endswith(suffix):
                fired = True
                raise RuntimeError(f"simulated crash {point}")
            return result

        monkeypatch.setattr(
            SecureEvidenceRoot, "create_immutable_bytes", fail_after_immutable_write
        )
    elif point == 5:
        original_fsync_run = StageAcquisitionUniverseCommit._fsync_run_dir

        def fail_after_run_fsync(secure: SecureEvidenceRoot, date: str, run: str) -> None:
            nonlocal fired
            original_fsync_run(secure, date, run)
            if not fired:
                fired = True
                raise RuntimeError("simulated crash 5")

        monkeypatch.setattr(
            StageAcquisitionUniverseCommit,
            "_fsync_run_dir",
            staticmethod(fail_after_run_fsync),
        )
    elif point == 6:
        original_write_temp = SecureEvidenceRoot._write_temp

        def fail_after_current_temp(
            self, parent_fd: int, final_name: str, data: bytes
        ) -> tuple[str, tuple[int, int]]:
            nonlocal fired
            result = original_write_temp(self, parent_fd, final_name, data)
            if not fired and final_name == "current.json":
                fired = True
                raise RuntimeError("simulated crash 6")
            return result

        monkeypatch.setattr(SecureEvidenceRoot, "_write_temp", fail_after_current_temp)
    elif point == 7:
        original_replace = os.replace

        def fail_after_current_replace(src, dst, *args, **kwargs):
            nonlocal fired
            result = original_replace(src, dst, *args, **kwargs)
            if not fired and dst == "current.json":
                fired = True
                raise RuntimeError("simulated crash 7")
            return result

        monkeypatch.setattr(os, "replace", fail_after_current_replace)
    else:
        original_replace = os.replace
        original_fsync_directory = SecureEvidenceRoot._fsync_directory
        replaced = False

        def mark_current_replace(src, dst, *args, **kwargs):
            nonlocal replaced
            result = original_replace(src, dst, *args, **kwargs)
            if dst == "current.json":
                replaced = True
            return result

        def fail_after_current_parent_fsync(fd: int) -> None:
            nonlocal fired
            original_fsync_directory(fd)
            if replaced and not fired:
                fired = True
                raise RuntimeError("simulated crash 8")

        monkeypatch.setattr(os, "replace", mark_current_replace)
        monkeypatch.setattr(
            SecureEvidenceRoot,
            "_fsync_directory",
            staticmethod(fail_after_current_parent_fsync),
        )

    with pytest.raises(RuntimeError, match=f"simulated crash {point}"):
        store.publish(payload, run_id=run_id, identity=IDENTITY)
    assert fired is True
    current_path = tmp_path / "current" / TRADE_DATE / STRICT_ROLE / "current.json"
    assert not current_path.exists() if point < 7 else current_path.is_file()

    recovered = store.publish(payload, run_id=run_id, identity=IDENTITY)
    assert recovered["status"] == "READY"
    assert store.read_strict_verified(TRADE_DATE)["run_id"] == run_id


def test_strict_multiple_committed_orphans_remain_ambiguous(tmp_path: Path, monkeypatch) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    original_replace = SecureEvidenceRoot.replace_current_cas
    original_scan = StageAcquisitionUniverseCommit._scan_orphans
    fired = False

    def leave_orphan(self, relative: str, *, expected_current_bytes_sha256, new_bytes):
        nonlocal fired
        if relative.startswith("current/") and not fired:
            fired = True
            raise RuntimeError("simulated current crash")
        return original_replace(
            self,
            relative,
            expected_current_bytes_sha256=expected_current_bytes_sha256,
            new_bytes=new_bytes,
        )

    monkeypatch.setattr(SecureEvidenceRoot, "replace_current_cas", leave_orphan)
    with pytest.raises(RuntimeError, match="simulated current crash"):
        store.publish(_physical_payload(store.root, "A.000001"), run_id="first", identity=IDENTITY)
    monkeypatch.setattr(SecureEvidenceRoot, "replace_current_cas", original_replace)
    fired = False
    monkeypatch.setattr(
        StageAcquisitionUniverseCommit, "_scan_orphans", lambda *_args: ([], False)
    )
    monkeypatch.setattr(SecureEvidenceRoot, "replace_current_cas", leave_orphan)
    with pytest.raises(RuntimeError, match="simulated current crash"):
        store.publish(_physical_payload(store.root, "A.000001"), run_id="second", identity=IDENTITY)
    monkeypatch.setattr(SecureEvidenceRoot, "replace_current_cas", original_replace)
    monkeypatch.setattr(
        StageAcquisitionUniverseCommit,
        "_scan_orphans",
        original_scan,
    )
    before = {
        path: path.read_bytes()
        for path in tmp_path.rglob("*.json")
    }
    with pytest.raises(StrictCommitError, match="multiple strict committed orphans"):
        store.publish(_physical_payload(store.root, "A.000001"), run_id="third", identity=IDENTITY)
    assert {path: path.read_bytes() for path in before} == before
