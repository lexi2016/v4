from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from domains.stage_preselection_projection import (
    StagePreselectionProjectionError,
    read_complete_a_set,
)
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.stage_acquisition_universe_store import (
    StageAcquisitionUniverseStore,
    build_stage_acquisition_universe,
)
from infrastructure.stage_acquisition_universe_contracts import (
    STRICT_POOL_SNAPSHOT_AUTHORITY,
    StrictAPreselectionSnapshot,
)
from infrastructure.stage_acquisition_universe_commit import EvidenceIdentity
from ops.materialize_stage_acquisition_universe import (
    materialize_stage_acquisition_universe,
)
from stage_center.input_contracts import A_POOL_CONTRACTS, REQUIRED_A_STAGE_POOL_IDS


TRADE_DATE = "20260902"
IDENTITY = EvidenceIdentity(
    owner_id="V3_5_STAGE_CENTER",
    producer_id="ops.materialize_stage_acquisition_universe",
    release_id="test-release",
    lane_id="A_SHARE_STAGE_ACQUISITION",
)


def _pool(
    pool_id: str,
    *codes: str,
    cannot_confirm: list[str] | None = None,
    stage_selection_eligible: bool | None = True,
    row_overrides: dict[str, object] | None = None,
    pool_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    status, producer_id, source_role = A_POOL_CONTRACTS[pool_id]
    rows: list[dict[str, object]] = []
    for code in codes or ("A.000001",):
        row: dict[str, object] = {
            "market": "A",
            "symbol": code,
            "pool_id": pool_id,
            "recommendation_status": "WATCH_ONLY",
        }
        if row_overrides:
            row.update(row_overrides)
        rows.append(row)
    payload: dict[str, object] = {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": TRADE_DATE,
        "pool_id": pool_id,
        "display_name": pool_id,
        "market": "A",
        "status": status,
        "producer_id": producer_id,
        "source_role": source_role,
        "source_path": f"fixture://{TRADE_DATE}/{pool_id}",
        "source_sha256": hashlib.sha256(pool_id.encode()).hexdigest(),
        "rows": rows,
        "cannot_confirm": list(cannot_confirm or []),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if stage_selection_eligible is not None:
        payload["stage_selection_eligible"] = stage_selection_eligible
    if pool_overrides:
        payload.update(pool_overrides)
    return payload


def _pools(
    *,
    duplicate_code: str | None = None,
    cannot_confirm_pool: str | None = None,
    ineligible_pool: str | None = None,
    row_overrides: dict[str, object] | None = None,
    pool_overrides: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    pools: list[dict[str, object]] = []
    for index, pool_id in enumerate(REQUIRED_A_STAGE_POOL_IDS, start=1):
        code = duplicate_code or f"A.{index:06d}"
        pools.append(
            _pool(
                pool_id,
                code,
                cannot_confirm=["UPSTREAM_UNVERIFIED"]
                if pool_id == cannot_confirm_pool
                else (["RESEARCH_ONLY_NO_BUY_GATE"] if pool_id == "a_share_baimao_research_map" else []),
                stage_selection_eligible=False if pool_id == ineligible_pool else True,
                row_overrides=row_overrides,
                pool_overrides=pool_overrides if pool_id == REQUIRED_A_STAGE_POOL_IDS[0] else None,
            )
        )
    if duplicate_code is not None:
        # A one-code fixture is useful for proving source-pool ordering.  Each
        # physical pool contains the same code exactly once.
        return pools
    return pools


def _projection(pools: list[dict[str, object]]) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for pool in pools:
        for row in pool["rows"]:
            code = str(row["symbol"])
            if code not in seen:
                rows.append(dict(row))
                seen.add(code)
    return {
        "ok": True,
        "trade_date": TRADE_DATE,
        "data_status": "READY_WITH_ROWS",
        "status": "READY_WITH_ROWS",
        "pools": deepcopy(pools),
        "a_all_pool_rows": rows,
        "a_all_pool_row_count": len(rows),
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _materialize_pools(root: Path, pools: list[dict[str, object]] | None = None) -> None:
    store = PreselectionPoolStore(root)
    for pool in pools or _pools():
        store.materialize(pool)


def _pool_path(root: Path, pool_id: str) -> Path:
    return root / "preselection_pools" / TRADE_DATE / f"{pool_id}.json"


def _receipt_path(root: Path, pool_id: str) -> Path:
    return root / "preselection_pools" / TRADE_DATE / "receipts" / f"{pool_id}.json"


def _strict_artifact_fixture(
    pools: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Make a strict-shaped artifact for store-boundary forgery tests."""

    projection = _projection(pools or _pools())
    artifact = build_stage_acquisition_universe(projection, TRADE_DATE)
    provenance: list[dict[str, object]] = []
    for pool in projection["pools"]:
        pool_id = str(pool["pool_id"])
        provenance.append(
            {
                "pool_id": pool_id,
                "status": A_POOL_CONTRACTS[pool_id][0],
                "row_count": len(pool["rows"]),
                "pool_sha256": hashlib.sha256(
                    json.dumps(
                        pool, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest(),
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
        json.dumps(
            provenance, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    artifact["policy_notes"] = []
    artifact["code_sources"] = {
        code: [REQUIRED_A_STAGE_POOL_IDS[0]] for code in artifact["codes"]
    }
    return artifact


def _refresh_provenance_sha(artifact: dict[str, object]) -> None:
    artifact["source_pool_provenance_sha256"] = hashlib.sha256(
        json.dumps(
            artifact["source_pool_provenance"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_artifact_whitespace_mutation_is_not_a_verified_snapshot(tmp_path: Path) -> None:
    _materialize_pools(tmp_path)
    artifact = _pool_path(tmp_path, REQUIRED_A_STAGE_POOL_IDS[0])
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    artifact.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with pytest.raises(StagePreselectionProjectionError, match="canonical"):
        read_complete_a_set(tmp_path, TRADE_DATE)


def test_receipt_whitespace_mutation_is_not_a_verified_snapshot(tmp_path: Path) -> None:
    _materialize_pools(tmp_path)
    receipt = _receipt_path(tmp_path, REQUIRED_A_STAGE_POOL_IDS[0])
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    receipt.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with pytest.raises(StagePreselectionProjectionError, match="canonical"):
        read_complete_a_set(tmp_path, TRADE_DATE)


def test_relative_path_or_required_receipt_mismatch_is_rejected(tmp_path: Path) -> None:
    _materialize_pools(tmp_path)
    receipt = _receipt_path(tmp_path, REQUIRED_A_STAGE_POOL_IDS[0])
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["artifact_path"] = "preselection_pools/other/artifact.json"
    receipt.write_bytes(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )

    with pytest.raises(StagePreselectionProjectionError, match="receipt"):
        read_complete_a_set(tmp_path, TRADE_DATE)


@pytest.mark.parametrize("row_pool_id", [None, "a_d1_fupan_watchlist_pool"])
def test_rows_must_bind_to_their_containing_pool(tmp_path: Path, row_pool_id: str | None) -> None:
    pools = _pools()
    row = pools[0]["rows"][0]
    if row_pool_id is None:
        row.pop("pool_id")
    else:
        row["pool_id"] = row_pool_id
    _materialize_pools(tmp_path, pools)

    with pytest.raises(StagePreselectionProjectionError, match="pool"):
        read_complete_a_set(tmp_path, TRADE_DATE)


def test_duplicate_code_is_retained_once_with_all_ordered_source_pools(tmp_path: Path) -> None:
    _materialize_pools(tmp_path, _pools(duplicate_code="A.000001"))
    snapshot = read_complete_a_set(tmp_path, TRADE_DATE)

    assert isinstance(snapshot, StrictAPreselectionSnapshot)
    assert snapshot["codes"] == ["A.000001"]
    assert snapshot["code_sources"]["A.000001"] == list(REQUIRED_A_STAGE_POOL_IDS)


def test_stale_snapshot_cannot_publish_after_physical_pool_deletion(tmp_path: Path) -> None:
    _materialize_pools(tmp_path)
    snapshot = read_complete_a_set(tmp_path, TRADE_DATE)
    _pool_path(tmp_path, REQUIRED_A_STAGE_POOL_IDS[-1]).unlink()

    with pytest.raises(ValueError, match="required A pool"):
        materialize_stage_acquisition_universe(
            tmp_path,
            TRADE_DATE,
            projection_reader=lambda *_args: snapshot,
            run_id="stale-snapshot-must-not-publish",
            release_id=IDENTITY.release_id,
        )
    assert not (tmp_path / "current").exists()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"cannot_confirm_pool": "a_d1_premarket_pool"},
        {"ineligible_pool": "a_d1_premarket_pool"},
    ],
)
def test_blocking_cannot_confirm_or_pool_ineligibility_prevents_strict_ready(
    tmp_path: Path, kwargs: dict[str, object]
) -> None:
    pools = _pools(**kwargs)
    _materialize_pools(tmp_path, pools)

    with pytest.raises(StagePreselectionProjectionError, match="cannot be confirmed"):
        read_complete_a_set(tmp_path, TRADE_DATE)


@pytest.mark.parametrize(
    "mutation",
    [
        {"future_return": 0.2},
        {"label_return": 0.2},
        {"post_event_score": 1.0},
    ],
)
def test_future_outcome_fields_are_rejected(tmp_path: Path, mutation: dict[str, object]) -> None:
    _materialize_pools(tmp_path, _pools(row_overrides=mutation))

    with pytest.raises(StagePreselectionProjectionError, match="future"):
        read_complete_a_set(tmp_path, TRADE_DATE)


@pytest.mark.parametrize(
    "pool_overrides,row_overrides",
    [
        ({"signal_date": "20260903"}, None),
        ({"target_date": "20260903"}, None),
        ({}, {"signal_date": "20260903"}),
        ({}, {"target_date": "20260903"}),
    ],
)
def test_future_signal_or_target_dates_are_rejected(
    tmp_path: Path,
    pool_overrides: dict[str, object],
    row_overrides: dict[str, object] | None,
) -> None:
    if "target_date" in pool_overrides:
        with pytest.raises(ValueError, match="target date"):
            _materialize_pools(
                tmp_path,
                _pools(pool_overrides=pool_overrides, row_overrides=row_overrides),
            )
        return
    _materialize_pools(
        tmp_path,
        _pools(pool_overrides=pool_overrides, row_overrides=row_overrides),
    )

    with pytest.raises(StagePreselectionProjectionError, match="date"):
        read_complete_a_set(tmp_path, TRADE_DATE)


def test_complete_valid_six_pool_snapshot_materializes(tmp_path: Path) -> None:
    _materialize_pools(tmp_path)
    snapshot = read_complete_a_set(tmp_path, TRADE_DATE)
    assert isinstance(snapshot, StrictAPreselectionSnapshot)
    assert tuple(snapshot.pool_ids) == REQUIRED_A_STAGE_POOL_IDS

    result = materialize_stage_acquisition_universe(
        tmp_path,
        TRADE_DATE,
        run_id="complete-six-pools",
        release_id=IDENTITY.release_id,
    )

    assert result["status"] == "READY"
    assert result["row_count"] == 6


def _seed_legacy_current(root: Path, artifact: dict[str, object], run_id: str) -> None:
    """Seed the old mapping-shaped current without using the guarded API.

    This models a legacy current that already exists on disk.  The helper is
    deliberately test-only: the production store must reject this artifact at
    every fresh or successor publication boundary.
    """

    store = StageAcquisitionUniverseStore(root)
    artifact_sha = hashlib.sha256(
        json.dumps(artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    paths = store._paths(TRADE_DATE, run_id)
    manifest = store._manifest_payload(TRADE_DATE, run_id, artifact, artifact_sha)
    manifest_sha = hashlib.sha256(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    receipt = store._receipt_payload(
        TRADE_DATE, run_id, artifact, artifact_sha, manifest_sha
    )
    receipt_sha = hashlib.sha256(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    for path, value in (
        (paths["artifact"], artifact),
        (paths["manifest"], manifest),
        (paths["receipt"], receipt),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        )
    verified = {
        "run_id": run_id,
        "artifact": artifact,
        "manifest": manifest,
        "receipt": receipt,
        "artifact_sha256": artifact_sha,
        "manifest_sha256": manifest_sha,
        "receipt_sha256": receipt_sha,
    }
    marker = store._commit_marker(TRADE_DATE, run_id, verified)
    marker_path = store._commit_path(TRADE_DATE, run_id)
    marker_path.write_bytes(
        json.dumps(marker, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    verified.update(
        commit=marker,
        commit_id=marker["commit_id"],
        commit_marker_relative=str(marker_path.relative_to(root)),
        commit_marker_sha256=hashlib.sha256(
            json.dumps(marker, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )
    current_path = store.current_path(TRADE_DATE)
    current_path.parent.mkdir(parents=True, exist_ok=True)
    current_path.write_bytes(
        json.dumps(
            store._pointer_payload(TRADE_DATE, verified),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )


def test_legacy_mapping_cannot_publish_a_fresh_current(tmp_path: Path) -> None:
    legacy = build_stage_acquisition_universe(_projection(_pools()), TRADE_DATE)
    assert legacy["authority"] == "LEGACY_NON_AUTHORITATIVE_PROJECTION"

    with pytest.raises(ValueError, match="STRICT_PHYSICAL_POOL_SNAPSHOT|required A pool"):
        StageAcquisitionUniverseStore(tmp_path).publish(
            legacy, run_id="legacy-fresh-must-not-publish", identity=IDENTITY
        )
    assert not (tmp_path / "current").exists()


def test_legacy_current_cannot_authorize_a_legacy_successor(tmp_path: Path) -> None:
    old = build_stage_acquisition_universe(
        _projection(_pools(duplicate_code="A.000001")), TRADE_DATE
    )
    _seed_legacy_current(tmp_path, old, "legacy-old")
    before = (tmp_path / "current" / TRADE_DATE).rglob("current.json")
    current_path = next(before)
    current_before = current_path.read_bytes()

    with pytest.raises(ValueError, match="strict snapshot|authority|cannot be confirmed"):
        materialize_stage_acquisition_universe(
            tmp_path,
            TRADE_DATE,
            projection_reader=lambda *_args: _projection(_pools()),
            run_id="legacy-successor-must-not-publish",
            release_id=IDENTITY.release_id,
        )

    assert current_path.read_bytes() == current_before
    assert not (tmp_path / "runs" / TRADE_DATE / "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V2" / "legacy-successor-must-not-publish").exists()


def test_forged_strict_pool_provenance_cannot_publish(tmp_path: Path) -> None:
    _materialize_pools(tmp_path)
    snapshot = read_complete_a_set(tmp_path, TRADE_DATE)
    forged = build_stage_acquisition_universe(snapshot)
    forged["source_pool_provenance"][0]["pool_id"] = "evil"
    forged["source_pool_provenance_sha256"] = hashlib.sha256(
        json.dumps(
            forged["source_pool_provenance"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    with pytest.raises(ValueError, match="provenance|pool"):
        StageAcquisitionUniverseStore(tmp_path).publish(
            forged, run_id="forged-strict-provenance", identity=IDENTITY
        )
    assert not (tmp_path / "current").exists()


@pytest.mark.parametrize(
    "field",
    ["future_price", "post_event_return", "label_value", "label_date"],
)
def test_future_label_and_post_event_field_families_are_rejected(
    tmp_path: Path, field: str
) -> None:
    _materialize_pools(tmp_path, _pools(row_overrides={field: "20260903"}))

    with pytest.raises(StagePreselectionProjectionError, match="future|label|post_event"):
        read_complete_a_set(tmp_path, TRADE_DATE)


def test_row_level_stage_selection_eligibility_must_be_true(tmp_path: Path) -> None:
    _materialize_pools(
        tmp_path, _pools(row_overrides={"stage_selection_eligible": False})
    )

    with pytest.raises(StagePreselectionProjectionError, match="eligible"):
        read_complete_a_set(tmp_path, TRADE_DATE)


def test_store_rejects_strict_shaped_artifact_without_physical_pools(
    tmp_path: Path,
) -> None:
    artifact = _strict_artifact_fixture()
    before = _tree_bytes(tmp_path)

    with pytest.raises(ValueError, match="required A pool"):
        StageAcquisitionUniverseStore(tmp_path).publish(
            artifact, run_id="strict-without-physical-pools", identity=IDENTITY
        )

    assert _tree_bytes(tmp_path) == before
    assert not (tmp_path / "current").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "artifact_raw_sha256",
        "manifest_raw_sha256",
        "receipt_raw_sha256",
        "artifact_relative_path",
        "manifest_relative_path",
        "receipt_relative_path",
        "codes",
        "code_sources",
    ],
)
def test_store_rejects_forged_strict_binding_against_real_pools(
    tmp_path: Path, mutation: str
) -> None:
    _materialize_pools(tmp_path)
    snapshot = read_complete_a_set(tmp_path, TRADE_DATE)
    artifact = build_stage_acquisition_universe(snapshot)
    if mutation in {
        "artifact_raw_sha256",
        "manifest_raw_sha256",
        "receipt_raw_sha256",
    }:
        artifact["source_pool_provenance"][0][mutation] = "f" * 64
        _refresh_provenance_sha(artifact)
    elif mutation.endswith("relative_path"):
        artifact["source_pool_provenance"][0][mutation] = (
            f"preselection_pools/{TRADE_DATE}/forged.json"
        )
        _refresh_provenance_sha(artifact)
    elif mutation == "codes":
        artifact["codes"] = ["A.999999"]
        artifact["row_count"] = 1
        artifact["codes_sha256"] = hashlib.sha256(
            json.dumps(
                artifact["codes"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        artifact["source_projection_row_count"] = 1
        artifact["code_sources"] = {
            "A.999999": [REQUIRED_A_STAGE_POOL_IDS[0]]
        }
    else:
        first_code = artifact["codes"][0]
        artifact["code_sources"][first_code] = [REQUIRED_A_STAGE_POOL_IDS[-1]]

    before = _tree_bytes(tmp_path)
    with pytest.raises(ValueError, match="physical|binding|provenance|pool"):
        StageAcquisitionUniverseStore(tmp_path).publish(
            artifact, run_id=f"forged-{mutation}", identity=IDENTITY
        )
    assert _tree_bytes(tmp_path) == before
    assert not (tmp_path / "current").exists()


def test_forged_strict_successor_cannot_advance_current(tmp_path: Path) -> None:
    _materialize_pools(tmp_path)
    snapshot = read_complete_a_set(tmp_path, TRADE_DATE)
    store = StageAcquisitionUniverseStore(tmp_path)
    first = store.publish(
        build_stage_acquisition_universe(snapshot),
        run_id="valid-current",
        identity=IDENTITY,
    )
    successor = deepcopy(build_stage_acquisition_universe(snapshot))
    successor["codes"] = [*successor["codes"], "A.999999"]
    successor["row_count"] = len(successor["codes"])
    successor["source_projection_row_count"] = len(successor["codes"])
    successor["codes_sha256"] = hashlib.sha256(
        json.dumps(
            successor["codes"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    successor["source_projection_sha256"] = "f" * 64
    successor["code_sources"]["A.999999"] = [REQUIRED_A_STAGE_POOL_IDS[0]]
    successor["source_pool_provenance"][0]["artifact_raw_sha256"] = "f" * 64
    _refresh_provenance_sha(successor)

    current_path = first["current_path"]
    current_before = current_path.read_bytes()
    before = _tree_bytes(tmp_path)
    with pytest.raises(ValueError, match="physical|binding|provenance|pool"):
        store.publish_successor(
            successor,
            run_id="forged-successor-must-not-advance",
            expected_current_sha256=hashlib.sha256(current_before).hexdigest(),
            reason="forged strict successor",
            identity=IDENTITY,
        )
    assert current_path.read_bytes() == current_before
    assert _tree_bytes(tmp_path) == before


def test_valid_physical_snapshot_publish_and_successor_succeed(tmp_path: Path) -> None:
    pools = _pools()
    # Keep later lanes duplicated so a same-day research-pool append extends
    # the deterministic union instead of inserting before later unique codes.
    pools[4]["rows"][0]["symbol"] = "A.000001"
    pools[5]["rows"][0]["symbol"] = "A.000002"
    _materialize_pools(tmp_path, pools)
    pool_store = PreselectionPoolStore(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    first_snapshot = read_complete_a_set(tmp_path, TRADE_DATE)
    first = store.publish(
        build_stage_acquisition_universe(first_snapshot),
        run_id="valid-old",
        identity=IDENTITY,
    )

    research = deepcopy(pools[3])
    research["source_path"] = (
        f"fixture://{TRADE_DATE}/a_share_research_recommendation_pool|"
        f"fixture://{TRADE_DATE}/a_share_research_recommendation_pool/next"
    )
    research["source_sha256"] = hashlib.sha256(
        research["source_path"].encode()
    ).hexdigest()
    research["rows"].append(
        {
            "market": "A",
            "symbol": "A.999999",
            "pool_id": "a_share_research_recommendation_pool",
            "recommendation_status": "WATCH_ONLY",
        }
    )
    pool_store.materialize(research)

    successor_snapshot = read_complete_a_set(tmp_path, TRADE_DATE)
    successor_artifact = build_stage_acquisition_universe(successor_snapshot)
    current_path = first["current_path"]
    result = store.publish_successor(
        successor_artifact,
        run_id="valid-new",
        expected_current_sha256=hashlib.sha256(current_path.read_bytes()).hexdigest(),
        reason="valid physical strict successor",
        identity=IDENTITY,
    )

    assert result["status"] == "SUPERSEDED"
    assert result["row_count"] == 5
    verified = store.read_strict_verified(TRADE_DATE, identity=IDENTITY)
    assert verified["artifact"]["codes"][-1] == "A.999999"
