from __future__ import annotations

import concurrent.futures
import hashlib
import json
import multiprocessing
import shutil
from pathlib import Path

import pytest

from infrastructure.stage_acquisition_universe_store import (
    ARTIFACT_ROLE,
    StageAcquisitionUniverseStore,
    build_stage_acquisition_universe,
)
from infrastructure.stage_acquisition_universe_contracts import (
    STRICT_POOL_SNAPSHOT_AUTHORITY,
)
from infrastructure.preselection_pool_store import PreselectionPoolStore
from domains.stage_preselection_projection import read_complete_a_set
from stage_center.candidate_input import CandidateInput, CandidateInputError, read_candidate_input
from stage_center.input_contracts import A_POOL_CONTRACTS, REQUIRED_A_STAGE_POOL_IDS


TRADE_DATE = "20260830"
_ORIGINAL_PUBLISH = StageAcquisitionUniverseStore.publish_legacy_v2
_ORIGINAL_PUBLISH_LEGACY_V2_SUCCESSOR = (
    StageAcquisitionUniverseStore.publish_legacy_v2_successor
)
COMMIT_FIELDS = (
    "commit_id",
    "commit_marker_relative",
    "commit_marker_sha256",
    "predecessor",
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _projection(*codes: str) -> dict[str, object]:
    rows = [
        {
            "market": "A",
            "symbol": code,
            "pool_id": "a_share_research_recommendation_pool",
            "recommendation_status": "WATCH_ONLY",
        }
        for code in codes
    ]
    contracts = {
        "a_d1_premarket_pool": (
            "V192_CANDIDATE_READY",
            "v3_shared_v192_consumer_v1",
            "SHARED_VERIFIED_V192",
        ),
        "a_d1_fupan_watchlist_pool": (
            "FUPAN_WATCHLIST_POOL_READY_DATA_PARTIAL",
            "v3_fupan_watchlist_contract_v1",
            "VERIFIED_D1_FUPAN_REVIEW",
        ),
        "a_d1_stage7_fenshi_review_pool": (
            "STAGE7_TAIL_POOL_READY_DATA_PARTIAL",
            "v3_stage7_tail_replay_contract_v1",
            "VERIFIED_D1_STAGE7_REPLAY",
        ),
        "a_share_research_recommendation_pool": (
            "RESEARCH_RECOMMENDATION_POOL_READY",
            "v3_5_hourly_research_window_v1",
            "VERIFIED_HOURLY_RESEARCH",
        ),
        "a_share_baimao_research_map": (
            "BAIMAO_RESEARCH_MAP_READY",
            "wechat_baimao_shared_projection_v1",
            "VERIFIED_BAIMAO_RESEARCH",
        ),
        "wechat_public_account_v3_preselect": (
            "WECHAT_V3_PRESELECT_READY",
            "v3_wechat_preselect_upstream_v1",
            "VERIFIED_WECHAT_RESEARCH",
        ),
    }
    pools = []
    for pool_id, (status, producer_id, source_role) in contracts.items():
        pool_rows = [
            {**row, "pool_id": pool_id}
            for row in (rows if pool_id == "a_d1_premarket_pool" else rows[:1])
        ]
        pools.append(
            {
                "schema_version": "v3_5.preselection_pool.v1",
                "pool_id": pool_id,
                "display_name": pool_id,
                "status": status,
                "producer_id": producer_id,
                "source_role": source_role,
                "source_path": f"fixture://{pool_id}",
                "source_sha256": "a" * 64,
                "trade_date": TRADE_DATE,
                "market": "A",
                "rows": pool_rows,
                "cannot_confirm": [],
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
    return {
        "ok": True,
        "trade_date": TRADE_DATE,
        "a_all_pool_rows": rows,
        "a_all_pool_row_count": len(rows),
        "data_status": "READY_WITH_ROWS",
        "status": "READY_WITH_ROWS",
        "cannot_confirm": [],
        "pools": pools,
    }


def _artifact(*codes: str) -> dict[str, object]:
    artifact = build_stage_acquisition_universe(_projection(*codes), TRADE_DATE)
    provenance: list[dict[str, object]] = []
    for pool_id in REQUIRED_A_STAGE_POOL_IDS:
        status = A_POOL_CONTRACTS[pool_id][0]
        provenance.append(
            {
                "pool_id": pool_id,
                "status": status,
                "row_count": len(codes),
                "pool_sha256": "a" * 64,
                "artifact_raw_sha256": hashlib.sha256(
                    f"{pool_id}:artifact".encode()
                ).hexdigest(),
                "manifest_raw_sha256": hashlib.sha256(
                    f"{pool_id}:manifest".encode()
                ).hexdigest(),
                "receipt_raw_sha256": hashlib.sha256(
                    f"{pool_id}:receipt".encode()
                ).hexdigest(),
                "artifact_relative_path": (
                    f"preselection_pools/{TRADE_DATE}/{pool_id}.json"
                ),
                "manifest_relative_path": f"preselection_pools/{TRADE_DATE}/manifest.json",
                "receipt_relative_path": (
                    f"preselection_pools/{TRADE_DATE}/receipts/{pool_id}.json"
                ),
            }
        )
    artifact["authority"] = STRICT_POOL_SNAPSHOT_AUTHORITY
    artifact["source_pool_provenance"] = provenance
    artifact["source_pool_provenance_sha256"] = hashlib.sha256(
        _canonical_bytes(provenance)
    ).hexdigest()
    artifact["policy_notes"] = []
    code_sources: dict[str, list[str]] = {
        code: [REQUIRED_A_STAGE_POOL_IDS[0]] for code in codes
    }
    if codes:
        code_sources[codes[0]] = list(REQUIRED_A_STAGE_POOL_IDS)
    artifact["code_sources"] = code_sources
    return artifact


def _materialize_source_pools(root: Path, codes: list[str]) -> None:
    source_root = Path(root) / "preselection_pools"
    if source_root.exists():
        shutil.rmtree(source_root)
    projection = _projection(*codes)
    primary = "a_share_research_recommendation_pool"
    first_code = codes[0]
    for pool in projection["pools"]:
        pool_id = str(pool["pool_id"])
        if pool_id == primary:
            pool["rows"] = [
                {
                    "market": "A",
                    "symbol": code,
                    "pool_id": primary,
                    "recommendation_status": "WATCH_ONLY",
                }
                for code in codes
            ]
            pool["source_path"] = f"fixture://{TRADE_DATE}/{primary}/source"
        else:
            pool["rows"] = [
                {
                    "market": "A",
                    "symbol": first_code,
                    "pool_id": pool_id,
                    "recommendation_status": "WATCH_ONLY",
                }
            ]
        pool["source_sha256"] = hashlib.sha256(
            str(pool["source_path"]).encode()
        ).hexdigest()
    source_store = PreselectionPoolStore(Path(root))
    for pool in projection["pools"]:
        source_store.materialize(pool)


def _strict_physical_artifact(store: StageAcquisitionUniverseStore, payload):
    codes = [str(code) for code in payload["codes"]]
    _materialize_source_pools(store.root, codes)
    return build_stage_acquisition_universe(
        read_complete_a_set(store.root, TRADE_DATE), TRADE_DATE
    )


@pytest.fixture(autouse=True)
def _bind_store_tests_to_physical_pools(monkeypatch):
    """Keep legacy store-unit fixtures backed by a real strict source tree."""

    def publish(store, payload, *args, **kwargs):
        strict = _strict_physical_artifact(store, payload)
        return _ORIGINAL_PUBLISH(store, strict, *args, **kwargs)

    def publish_legacy_v2_successor(store, payload, *args, **kwargs):
        strict = _strict_physical_artifact(store, payload)
        return _ORIGINAL_PUBLISH_LEGACY_V2_SUCCESSOR(store, strict, *args, **kwargs)

    monkeypatch.setattr(StageAcquisitionUniverseStore, "publish", publish)
    monkeypatch.setattr(
        StageAcquisitionUniverseStore,
        "publish_legacy_v2_successor",
        publish_legacy_v2_successor,
    )


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(_canonical_bytes(value))


def _publish_in_process(args: tuple[str, dict[str, object], str]) -> dict[str, object]:
    root, payload, run_id = args
    store = StageAcquisitionUniverseStore(Path(root))
    strict = build_stage_acquisition_universe(
        read_complete_a_set(store.root, TRADE_DATE), TRADE_DATE
    )
    return _ORIGINAL_PUBLISH(store, strict, run_id=run_id)


def _trio_and_current(store: StageAcquisitionUniverseStore, run_id: str) -> dict[str, bytes]:
    paths = store._paths(TRADE_DATE, run_id)
    result = {name: path.read_bytes() for name, path in paths.items()}
    result["current"] = store.current_path(TRADE_DATE).read_bytes()
    result["commit"] = store._commit_path(TRADE_DATE, run_id).read_bytes()
    return result


def test_publish_commits_trio_then_marker_then_current(tmp_path: Path, monkeypatch) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    payload = _artifact("A.000001", "A.000002")
    writes: list[str] = []
    original_write = store._write

    def record_write(relative: str, value: object) -> None:
        writes.append(relative)
        original_write(relative, value)

    monkeypatch.setattr(store, "_write", record_write)
    result = store.publish(payload, run_id="run-a")

    assert result["status"] == "READY"
    assert result["idempotent"] is False
    assert writes[-2].endswith("/commit.json")
    assert writes[-1] == f"current/{TRADE_DATE}/{ARTIFACT_ROLE}/current.json"
    assert all(
        writes.index(f"runs/{TRADE_DATE}/{ARTIFACT_ROLE}/run-a/{name}.json")
        < writes.index(writes[-2])
        for name in ("artifact", "manifest", "receipt")
    )

    marker = _read_json(store._commit_path(TRADE_DATE, "run-a"))
    current = _read_json(store.current_path(TRADE_DATE))
    assert marker["schema_version"] == "v3_5.stage_acquisition_universe.commit.v1"
    assert marker["status"] == "COMMITTED"
    assert marker["predecessor"] is None
    assert marker["commit_id"] == current["commit_id"]
    assert current["commit_marker_relative"].endswith("/commit.json")
    assert current["commit_marker_sha256"] == hashlib.sha256(
        _canonical_bytes(marker)
    ).hexdigest()
    assert store.read_verified(TRADE_DATE)["commit_id"] == marker["commit_id"]


def test_marker_after_trio_recovers_current_only_crash(tmp_path: Path, monkeypatch) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    payload = _artifact("A.000001")
    original_write = store._write

    def fail_current(relative: str, value: object) -> None:
        if relative.startswith("current/"):
            raise RuntimeError("simulated current crash")
        original_write(relative, value)

    monkeypatch.setattr(store, "_write", fail_current)
    with pytest.raises(RuntimeError, match="simulated current crash"):
        store.publish(payload, run_id="recoverable")
    assert not store.current_path(TRADE_DATE).exists()
    assert store._commit_path(TRADE_DATE, "recoverable").is_file()

    monkeypatch.setattr(store, "_write", original_write)
    recovered = store.publish(payload, run_id="recoverable")
    assert recovered["status"] == "READY"
    assert recovered["idempotent"] is False
    assert store.read_verified(TRADE_DATE)["run_id"] == "recoverable"


def test_staged_trio_recovers_when_marker_create_is_interrupted(
    tmp_path: Path, monkeypatch
) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    payload = _artifact("A.000001")
    original_write = store._write

    def fail_marker(relative: str, value: object) -> None:
        if relative.endswith("/commit.json"):
            raise RuntimeError("simulated marker crash")
        original_write(relative, value)

    monkeypatch.setattr(store, "_write", fail_marker)
    with pytest.raises(RuntimeError, match="simulated marker crash"):
        store.publish(payload, run_id="staged")
    paths = store._paths(TRADE_DATE, "staged")
    assert all(path.is_file() for path in paths.values())
    assert not store._commit_path(TRADE_DATE, "staged").exists()
    assert not store.current_path(TRADE_DATE).exists()

    monkeypatch.setattr(store, "_write", original_write)
    recovered = store.publish(payload, run_id="staged")
    assert recovered["status"] == "READY"
    assert store.read_verified(TRADE_DATE)["commit_id"]


@pytest.mark.parametrize("component", ("artifact", "manifest", "receipt", "commit", "current"))
def test_store_rejects_final_symlink_for_every_evidence_component(
    tmp_path: Path, component: str
) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    store.publish(_artifact("A.000001"), run_id="symlink-final")
    if component == "current":
        target = store.current_path(TRADE_DATE)
    elif component == "commit":
        target = store._commit_path(TRADE_DATE, "symlink-final")
    else:
        target = store._paths(TRADE_DATE, "symlink-final")[component]
    outside = tmp_path.parent / f"outside-{component}.json"
    outside.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        store.read_verified(TRADE_DATE)


@pytest.mark.parametrize("parent_name", ("runs", "current"))
def test_store_rejects_parent_symlink_before_writing(tmp_path: Path, parent_name: str) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    outside = tmp_path.parent / f"outside-parent-{parent_name}"
    outside.mkdir()
    (tmp_path / parent_name).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        store.publish(_artifact("A.000001"), run_id=f"parent-{parent_name}")
    assert not list(outside.rglob("*.json"))


def test_corrupt_marker_fails_closed_without_replacement(tmp_path: Path, monkeypatch) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    payload = _artifact("A.000001")
    original_write = store._write

    def fail_current(relative: str, value: object) -> None:
        if relative.startswith("current/"):
            raise RuntimeError("simulated current crash")
        original_write(relative, value)

    monkeypatch.setattr(store, "_write", fail_current)
    with pytest.raises(RuntimeError):
        store.publish(payload, run_id="corrupt-marker")
    marker_path = store._commit_path(TRADE_DATE, "corrupt-marker")
    marker_path.write_bytes(b"{}")
    before = marker_path.read_bytes()
    monkeypatch.setattr(store, "_write", original_write)
    with pytest.raises(ValueError, match="commit marker"):
        store.publish(payload, run_id="corrupt-marker")
    assert marker_path.read_bytes() == before
    assert not store.current_path(TRADE_DATE).exists()


def test_cas_conflict_preserves_winner_and_same_artifact_is_idempotent(tmp_path: Path) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    winner = _artifact("A.000001")
    loser = _artifact("A.000001", "A.000002")
    store.publish(winner, run_id="winner")
    before = _trio_and_current(store, "winner")

    same = store.publish(winner, run_id="other-run")
    assert same["idempotent"] is True
    assert same["run_id"] == "winner"
    with pytest.raises(ValueError, match="exact slot conflict"):
        store.publish(loser, run_id="loser")
    assert _trio_and_current(store, "winner") == before
    assert not store._run_dir(TRADE_DATE, "loser").exists()


def test_same_day_403_to_421_requires_successor_cas_path(tmp_path: Path) -> None:
    """The old immutable publish path must expose the exact-slot conflict.

    The successor API is intentionally introduced by the implementation after
    this red test: a same-day all-A aggregate may evolve, but only with an
    explicit expected-current CAS and immutable supersession evidence.
    """

    store = StageAcquisitionUniverseStore(tmp_path)
    old_codes = [f"A.{index:06d}" for index in range(1, 404)]
    new_codes = [f"A.{index:06d}" for index in range(1, 422)]
    store.publish(_artifact(*old_codes), run_id="old-403")
    current_path = store.current_path(TRADE_DATE)
    expected_current_sha256 = hashlib.sha256(current_path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="exact slot conflict"):
        store.publish(_artifact(*new_codes), run_id="new-421")

    result = store.publish_legacy_v2_successor(
        _artifact(*new_codes),
        run_id="new-421",
        expected_current_sha256=expected_current_sha256,
        reason="same-day all-A preselection aggregate grew from 403 to 421",
    )
    assert result["status"] == "SUPERSEDED"
    assert result["row_count"] == 421


def test_successor_records_predecessor_and_preserves_old_run_bytes(tmp_path: Path) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    old_codes = [f"A.{index:06d}" for index in range(1, 404)]
    new_codes = [f"A.{index:06d}" for index in range(1, 422)]
    store.publish(_artifact(*old_codes), run_id="old-403")
    old_paths = _trio_and_current(store, "old-403")
    current_path = store.current_path(TRADE_DATE)
    expected_current_sha256 = hashlib.sha256(current_path.read_bytes()).hexdigest()

    result = store.publish_legacy_v2_successor(
        _artifact(*new_codes),
        run_id="new-421",
        expected_current_sha256=expected_current_sha256,
        reason="same-day all-A preselection aggregate grew from 403 to 421",
    )

    assert result["idempotent"] is False
    assert result["supersession_receipt_path"].is_file()
    current = _read_json(current_path)
    assert current["predecessor"] is None
    assert _trio_and_current(store, "old-403")["artifact"] == old_paths["artifact"]
    receipt = _read_json(result["supersession_receipt_path"])
    assert receipt["status"] == "SUPERSEDED"
    assert receipt["previous_run_id"] == "old-403"
    assert receipt["successor_run_id"] == "new-421"
    assert receipt["previous_row_count"] == 403
    assert receipt["successor_row_count"] == 421
    predecessor = receipt["predecessor"]
    assert predecessor["run_id"] == "old-403"
    assert predecessor["row_count"] == 403
    assert predecessor["artifact_sha256"] == hashlib.sha256(
        old_paths["artifact"]
    ).hexdigest()
    assert predecessor["current_sha256"] == expected_current_sha256
    assert receipt["production_allowed"] is False
    assert receipt["buy_gate_updated"] is False
    assert receipt["orders_sent"] is False


def test_successor_wrong_expected_sha_fails_closed_without_moving_current(
    tmp_path: Path,
) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    old_codes = [f"A.{index:06d}" for index in range(1, 404)]
    new_codes = [f"A.{index:06d}" for index in range(1, 422)]
    store.publish(_artifact(*old_codes), run_id="old-403")
    current_path = store.current_path(TRADE_DATE)
    before = current_path.read_bytes()

    with pytest.raises(ValueError, match="SHA mismatch"):
        store.publish_legacy_v2_successor(
            _artifact(*new_codes),
            run_id="new-421",
            expected_current_sha256="0" * 64,
            reason="same-day all-A preselection aggregate grew from 403 to 421",
        )

    assert current_path.read_bytes() == before
    assert not store._run_dir(TRADE_DATE, "new-421").exists()
    assert not (tmp_path / "supersessions").exists()


def test_repeating_same_successor_request_is_idempotent(tmp_path: Path) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    old_codes = [f"A.{index:06d}" for index in range(1, 404)]
    new_codes = [f"A.{index:06d}" for index in range(1, 422)]
    store.publish(_artifact(*old_codes), run_id="old-403")
    expected = hashlib.sha256(
        store.current_path(TRADE_DATE).read_bytes()
    ).hexdigest()
    successor = _artifact(*new_codes)
    first = store.publish_legacy_v2_successor(
        successor,
        run_id="new-421",
        expected_current_sha256=expected,
        reason="same-day all-A preselection aggregate grew from 403 to 421",
    )
    current_bytes = store.current_path(TRADE_DATE).read_bytes()

    second = store.publish_legacy_v2_successor(
        successor,
        run_id="retry-with-a-different-run-id",
        expected_current_sha256=expected,
        reason="same-day all-A preselection aggregate grew from 403 to 421",
    )

    assert first["status"] == "SUPERSEDED"
    assert second["status"] == "SUPERSEDED"
    assert second["idempotent"] is True
    assert second["run_id"] == "new-421"
    assert store.current_path(TRADE_DATE).read_bytes() == current_bytes


def test_marker_exists_race_never_replaces_preexisting_bytes(tmp_path: Path, monkeypatch) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    payload = _artifact("A.000001")
    original_write = store._write
    rival = b'{"rival":true}'
    inserted = False

    def race(relative: str, value: object) -> None:
        nonlocal inserted
        if relative.endswith("/commit.json") and not inserted:
            marker_path = store._commit_path(TRADE_DATE, "marker-race")
            marker_path.parent.mkdir(parents=True, exist_ok=True)
            marker_path.write_bytes(rival)
            inserted = True
        original_write(relative, value)

    monkeypatch.setattr(store, "_write", race)
    with pytest.raises(ValueError, match="commit marker"):
        store.publish(payload, run_id="marker-race")
    marker_path = store._commit_path(TRADE_DATE, "marker-race")
    assert marker_path.read_bytes() == rival
    assert not store.current_path(TRADE_DATE).exists()


@pytest.mark.parametrize("component", ("artifact", "manifest", "receipt"))
def test_trio_exists_race_never_replaces_preexisting_bytes(
    tmp_path: Path, component: str, monkeypatch
) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    payload = _artifact("A.000001")
    original_write = store._write
    rival = b'{"rival":true}'
    inserted = False

    def race(relative: str, value: object) -> None:
        nonlocal inserted
        if relative.endswith(f"/{component}.json") and not inserted:
            target = store._paths(TRADE_DATE, "trio-race")[component]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(rival)
            inserted = True
        original_write(relative, value)

    monkeypatch.setattr(store, "_write", race)
    with pytest.raises(ValueError, match="immutable"):
        store.publish(payload, run_id="trio-race")
    target = store._paths(TRADE_DATE, "trio-race")[component]
    assert target.read_bytes() == rival
    assert not store.current_path(TRADE_DATE).exists()


def test_current_exists_race_preserves_preexisting_winner_bytes(
    tmp_path: Path, monkeypatch
) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    payload = _artifact("A.000001")
    store.publish(payload, run_id="winner")
    current_path = store.current_path(TRADE_DATE)
    rival = current_path.read_bytes()
    current_path.unlink()
    original_write = store._write
    inserted = False

    def race(relative: str, value: object) -> None:
        nonlocal inserted
        if relative.startswith("current/") and not inserted:
            current_path.parent.mkdir(parents=True, exist_ok=True)
            current_path.write_bytes(rival)
            inserted = True
        original_write(relative, value)

    monkeypatch.setattr(store, "_write", race)
    result = store.publish(payload, run_id="candidate")
    assert result["idempotent"] is True
    assert result["run_id"] == "winner"
    assert current_path.read_bytes() == rival


def _leave_committed_orphan(
    store: StageAcquisitionUniverseStore,
    payload: dict[str, object],
    run_id: str,
    monkeypatch,
) -> None:
    original_write = store._write

    def fail_current(relative: str, value: object) -> None:
        if relative.startswith("current/"):
            raise RuntimeError("simulated current crash")
        original_write(relative, value)

    monkeypatch.setattr(store, "_write", fail_current)
    with pytest.raises(RuntimeError, match="simulated current crash"):
        store.publish(payload, run_id=run_id)
    monkeypatch.setattr(store, "_write", original_write)


def test_missing_current_reuses_committed_orphan_run(tmp_path: Path, monkeypatch) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    payload = _artifact("A.000001")
    _leave_committed_orphan(store, payload, "orphan", monkeypatch)

    result = store.publish(payload, run_id="new-run")

    assert result["run_id"] == "orphan"
    assert store.read_verified(TRADE_DATE)["run_id"] == "orphan"
    assert not store._run_dir(TRADE_DATE, "new-run").exists()


def test_missing_current_orphan_conflicts_with_different_payload(
    tmp_path: Path, monkeypatch
) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    _leave_committed_orphan(store, _artifact("A.000001"), "orphan", monkeypatch)

    with pytest.raises(ValueError, match="exact slot conflict"):
        store.publish(_artifact("A.000002"), run_id="new-run")

    assert not store.current_path(TRADE_DATE).exists()
    assert not store._run_dir(TRADE_DATE, "new-run").exists()


def test_partial_orphan_fails_closed_for_new_run(tmp_path: Path, monkeypatch) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    payload = _artifact("A.000001")
    original_write = store._write

    def fail_marker(relative: str, value: object) -> None:
        if relative.endswith("/commit.json"):
            raise RuntimeError("simulated marker crash")
        original_write(relative, value)

    monkeypatch.setattr(store, "_write", fail_marker)
    with pytest.raises(RuntimeError, match="simulated marker crash"):
        store.publish(payload, run_id="partial")
    monkeypatch.setattr(store, "_write", original_write)

    with pytest.raises(ValueError, match="orphan"):
        store.publish(payload, run_id="new-run")
    assert not store.current_path(TRADE_DATE).exists()


def test_malformed_committed_orphan_fails_closed(tmp_path: Path, monkeypatch) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    payload = _artifact("A.000001")
    _leave_committed_orphan(store, payload, "malformed", monkeypatch)
    store._commit_path(TRADE_DATE, "malformed").write_bytes(b"{}")

    with pytest.raises(ValueError, match="commit marker"):
        store.publish(payload, run_id="new-run")
    assert not store.current_path(TRADE_DATE).exists()


def test_multiple_committed_orphans_fail_closed(tmp_path: Path, monkeypatch) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    payload = _artifact("A.000001")
    _leave_committed_orphan(store, payload, "first", monkeypatch)
    with monkeypatch.context() as bypass_recovery:
        bypass_recovery.setattr(store, "_orphan_state", lambda *_args: None)
        _leave_committed_orphan(store, payload, "second", bypass_recovery)

    with pytest.raises(ValueError, match="multiple"):
        store.publish(payload, run_id="new-run")
    assert not store.current_path(TRADE_DATE).exists()


def test_concurrent_same_payload_has_one_create_and_one_idempotent_result(tmp_path: Path) -> None:
    payload = _artifact("A.000001", "A.000002")
    _materialize_source_pools(tmp_path, ["A.000001", "A.000002"])
    args = [(str(tmp_path), payload, "concurrent") for _ in range(2)]
    context = multiprocessing.get_context("fork")
    with concurrent.futures.ProcessPoolExecutor(max_workers=2, mp_context=context) as pool:
        results = list(pool.map(_publish_in_process, args))
    assert sorted(bool(result["idempotent"]) for result in results) == [False, True]
    assert StageAcquisitionUniverseStore(tmp_path).read_verified(TRADE_DATE)["commit_id"]


def test_candidate_reader_supports_marker_and_legacy_v2(tmp_path: Path) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    store.publish(_artifact("A.000001"), run_id="candidate")
    current_path = store.current_path(TRADE_DATE)
    current = _read_json(current_path)
    current_sha = hashlib.sha256(current_path.read_bytes()).hexdigest()
    candidate = read_candidate_input(
        tmp_path,
        TRADE_DATE,
        expected_current_sha256=current_sha,
        compatibility_mode="LEGACY_V2",
    )
    assert candidate.commit_id == current["commit_id"]

    legacy = {key: value for key, value in current.items() if key not in COMMIT_FIELDS}
    _write_json(current_path, legacy)
    old_candidate = read_candidate_input(
        tmp_path, TRADE_DATE, compatibility_mode="LEGACY_V2"
    )
    assert old_candidate.commit_id is None


@pytest.mark.parametrize("tamper", ("partial", "marker_id", "marker_sha", "path"))
def test_candidate_reader_rejects_partial_or_tampered_marker(tmp_path: Path, tamper: str) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    store.publish(_artifact("A.000001"), run_id="candidate")
    current_path = store.current_path(TRADE_DATE)
    current = _read_json(current_path)
    marker_path = store._commit_path(TRADE_DATE, "candidate")
    marker = _read_json(marker_path)
    if tamper == "partial":
        current.pop("commit_marker_sha256")
        _write_json(current_path, current)
    elif tamper == "marker_id":
        marker["commit_id"] = "f" * 64
        _write_json(marker_path, marker)
    elif tamper == "marker_sha":
        current["commit_marker_sha256"] = "f" * 64
        _write_json(current_path, current)
    else:
        current["commit_marker_relative"] = "runs/../outside/commit.json"
        _write_json(current_path, current)
    with pytest.raises(CandidateInputError):
        read_candidate_input(
            tmp_path, TRADE_DATE, compatibility_mode="LEGACY_V2"
        )


def test_candidate_reader_keeps_expected_sha_and_manual_constructor_compatibility(
    tmp_path: Path,
) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    store.publish(_artifact("A.000001"), run_id="candidate")
    current_path = store.current_path(TRADE_DATE)
    current_sha = hashlib.sha256(current_path.read_bytes()).hexdigest()
    with pytest.raises(CandidateInputError, match="current.json SHA mismatch"):
        read_candidate_input(
            tmp_path,
            TRADE_DATE,
            expected_current_sha256="0" * 64,
            compatibility_mode="LEGACY_V2",
        )
    candidate = CandidateInput(
        root=tmp_path,
        trade_date=TRADE_DATE,
        current_relative="current.json",
        current_sha256=current_sha,
        run_id="legacy",
        codes=("A.000001",),
        artifact_sha256="a" * 64,
        manifest_sha256="b" * 64,
        receipt_sha256="c" * 64,
        source_projection_sha256="d" * 64,
        source_evidence=(),
    )
    assert candidate.commit_id is None
