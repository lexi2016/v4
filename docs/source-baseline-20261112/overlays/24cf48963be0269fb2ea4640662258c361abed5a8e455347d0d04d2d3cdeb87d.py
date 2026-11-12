from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from domains.stage_preselection_projection import read_complete_a_set
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.secure_evidence_fs import SecureEvidenceRoot
from infrastructure.stage_acquisition_universe_store import (
    StageAcquisitionUniverseStore,
    build_stage_acquisition_universe,
)
from infrastructure.stage_acquisition_universe_commit import (
    EvidenceIdentity,
    StageAcquisitionUniverseCommit,
    StrictCommitError,
)
from ops.materialize_stage_acquisition_universe import (
    materialize_stage_acquisition_universe,
    materialize_stage_acquisition_universe_successor,
)
from stage_center.input_contracts import A_POOL_CONTRACTS, REQUIRED_A_STAGE_POOL_IDS


TRADE_DATE = "20260904"


def _identity() -> EvidenceIdentity:
    return EvidenceIdentity(
        owner_id="V3_5_STAGE_CENTER",
        producer_id="ops.materialize_stage_acquisition_universe",
        release_id="test-release",
        lane_id="A_SHARE_STAGE_ACQUISITION",
    )


def _pool(pool_id: str, code: str) -> dict[str, object]:
    status, producer_id, source_role = A_POOL_CONTRACTS[pool_id]
    return {
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
        "rows": [
            {
                "market": "A",
                "symbol": code,
                "pool_id": pool_id,
                "recommendation_status": "WATCH_ONLY",
            }
        ],
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _materialize_pools(root: Path) -> None:
    pool_store = PreselectionPoolStore(root)
    codes = ("A.000001", "A.000002", "A.000003", "A.000004", "A.000001", "A.000002")
    for code, pool_id in zip(codes, REQUIRED_A_STAGE_POOL_IDS):
        pool_store.materialize(_pool(pool_id, code))


def _artifact(root: Path) -> dict[str, object]:
    return build_stage_acquisition_universe(
        read_complete_a_set(root, TRADE_DATE), TRADE_DATE
    )


def _append_research_pool(root: Path) -> None:
    research_id = "a_share_research_recommendation_pool"
    source_store = PreselectionPoolStore(root)
    updated = _pool(research_id, "A.000004")
    updated["source_path"] = (
        f"fixture://{TRADE_DATE}/{research_id}|fixture://{TRADE_DATE}/{research_id}/next"
    )
    updated["source_sha256"] = hashlib.sha256(
        str(updated["source_path"]).encode()
    ).hexdigest()
    updated["rows"] = [
        {
            "market": "A",
            "symbol": "A.000004",
            "pool_id": research_id,
            "recommendation_status": "WATCH_ONLY",
        },
        {
            "market": "A",
            "symbol": "A.999999",
            "pool_id": research_id,
            "recommendation_status": "WATCH_ONLY",
        },
    ]
    source_store.materialize(updated)


def _refresh_research_metadata_without_rows(root: Path) -> None:
    research_id = "a_share_research_recommendation_pool"
    source_store = PreselectionPoolStore(root)
    updated = source_store.read_pool(TRADE_DATE, research_id)
    updated["source_path"] = (
        f"fixture://{TRADE_DATE}/{research_id}|"
        f"fixture://{TRADE_DATE}/{research_id}/same-rows"
    )
    updated["source_sha256"] = hashlib.sha256(
        str(updated["source_path"]).encode()
    ).hexdigest()
    source_store.materialize(updated)


def test_strict_successor_binds_raw_current_and_records_predecessor_lineage(
    tmp_path: Path,
) -> None:
    _materialize_pools(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    first = store.publish(_artifact(tmp_path), run_id="strict-old", identity=_identity())
    current_path = first["current_path"]
    current_before = current_path.read_bytes()
    current_sha = hashlib.sha256(current_before).hexdigest()

    _append_research_pool(tmp_path)
    successor = _artifact(tmp_path)

    result = store.publish_successor(
        successor,
        expected_current_sha256=current_sha,
        reason="same-day physical research pool append",
        run_id="strict-new",
        identity=_identity(),
    )

    assert result["status"] == "SUPERSEDED"
    assert result["run_id"] == "strict-new"
    current = store.read_strict_verified(TRADE_DATE)["current"]
    assert current["previous_commit_id"] == first["commit_id"]
    assert current["previous_current_bytes_sha256"] == current_sha
    assert current["run_id"] != "strict-old"
    receipt = result["supersession_receipt"]
    assert receipt["previous_commit_id"] == first["commit_id"]
    assert receipt["previous_current_bytes_sha256"] == current_sha


def test_store_successor_without_identity_fails_closed_and_keeps_current_unchanged(
    tmp_path: Path,
) -> None:
    """The public store successor API cannot silently fall back to V2."""

    _materialize_pools(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    first = store.publish(_artifact(tmp_path), run_id="strict-old", identity=_identity())
    current_before = first["current_path"].read_bytes()
    current_sha = hashlib.sha256(current_before).hexdigest()
    _append_research_pool(tmp_path)

    with pytest.raises(StrictCommitError, match="evidence identity"):
        store.publish_successor(
            _artifact(tmp_path),
            expected_current_sha256=current_sha,
            reason="missing identity must fail closed",
            run_id="strict-no-identity",
        )

    assert first["current_path"].read_bytes() == current_before
    assert not (
        tmp_path
        / "runs"
        / TRADE_DATE
        / "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V3"
        / "strict-no-identity"
    ).exists()


def test_explicit_legacy_v2_successor_rejects_artifact_sha_cas_token(
    tmp_path: Path,
) -> None:
    _materialize_pools(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    first = store.publish_legacy_v2(_artifact(tmp_path), run_id="legacy-old")
    current_path = store.current_path(TRADE_DATE)
    current_before = current_path.read_bytes()
    _append_research_pool(tmp_path)

    with pytest.raises(ValueError, match="artifact SHA"):
        store.publish_legacy_v2_successor(
            _artifact(tmp_path),
            expected_current_sha256=first["artifact_sha256"],
            reason="legacy artifact SHA must not be a CAS token",
            run_id="legacy-invalid-cas",
        )

    assert current_path.read_bytes() == current_before


@pytest.mark.parametrize(
    ("extension", "message"),
    (
        ({"review": {"order": {"symbol": "A.999999"}}}, "unsafe action"),
        ({"metrics": {"future_return": 0.25}}, "unsafe outcome"),
    ),
)
def test_strict_initial_rejects_recursive_unsafe_extensions_before_current(
    tmp_path: Path, extension: dict[str, object], message: str
) -> None:
    _materialize_pools(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    artifact = _artifact(tmp_path)
    artifact["extensions"] = extension

    with pytest.raises(StrictCommitError, match=message):
        store.publish(artifact, run_id="strict-unsafe-initial", identity=_identity())

    assert not (tmp_path / "current").exists()
    assert not (
        tmp_path
        / "runs"
        / TRADE_DATE
        / "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V3"
        / "strict-unsafe-initial"
    ).exists()


@pytest.mark.parametrize(
    ("extension", "message"),
    (
        ({"review": [{"SIGNAL": "WATCH_ONLY"}]}, "unsafe action"),
        ({"review": {"post_event_score": 0.9}}, "unsafe outcome"),
    ),
)
def test_strict_successor_rejects_recursive_unsafe_extensions_without_cas(
    tmp_path: Path, extension: dict[str, object], message: str
) -> None:
    _materialize_pools(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    first = store.publish(_artifact(tmp_path), run_id="strict-old", identity=_identity())
    current_before = first["current_path"].read_bytes()
    current_sha = hashlib.sha256(current_before).hexdigest()
    _append_research_pool(tmp_path)
    successor = _artifact(tmp_path)
    successor["extensions"] = extension

    with pytest.raises(StrictCommitError, match=message):
        store.publish_successor(
            successor,
            expected_current_sha256=current_sha,
            reason="unsafe extension must fail closed",
            run_id="strict-unsafe-successor",
            identity=_identity(),
        )

    assert first["current_path"].read_bytes() == current_before
    assert not (
        tmp_path
        / "runs"
        / TRADE_DATE
        / "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V3"
        / "strict-unsafe-successor"
    ).exists()


def test_materializer_successor_wrapper_uses_current_raw_sha(
    tmp_path: Path,
) -> None:
    _materialize_pools(tmp_path)
    first = materialize_stage_acquisition_universe(
        tmp_path,
        TRADE_DATE,
        run_id="strict-old",
        release_id="test-release",
    )
    current_sha = hashlib.sha256(first["current_path"].read_bytes()).hexdigest()
    _append_research_pool(tmp_path)

    result = materialize_stage_acquisition_universe_successor(
        tmp_path,
        TRADE_DATE,
        expected_current_sha256=current_sha,
        reason="materializer wrapper successor",
        run_id="strict-new",
        release_id="test-release",
    )

    assert result["status"] == "SUPERSEDED"
    assert result["run_id"] == "strict-new"


def test_strict_successor_retry_is_idempotent_only_for_verified_lineage(
    tmp_path: Path,
) -> None:
    _materialize_pools(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    store.publish(_artifact(tmp_path), run_id="strict-old", identity=_identity())
    current_path = store.read_strict_verified(TRADE_DATE)["current_path"]
    expected = hashlib.sha256(current_path.read_bytes()).hexdigest()
    _append_research_pool(tmp_path)
    successor = _artifact(tmp_path)

    first = store.publish_successor(
        successor,
        expected_current_sha256=expected,
        reason="same-day physical research pool append",
        run_id="strict-new",
        identity=_identity(),
    )
    current_after = current_path.read_bytes()
    second = store.publish_successor(
        successor,
        expected_current_sha256=expected,
        reason="same-day physical research pool append",
        run_id="different-retry-run",
        identity=_identity(),
    )

    assert first["status"] == "SUPERSEDED"
    assert second["status"] == "SUPERSEDED"
    assert second["idempotent"] is True
    assert second["run_id"] == "strict-new"
    assert current_path.read_bytes() == current_after


def test_strict_successor_rejects_artifact_sha_as_cas_token(tmp_path: Path) -> None:
    _materialize_pools(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    first = store.publish(_artifact(tmp_path), run_id="strict-old", identity=_identity())
    current_before = first["current_path"].read_bytes()

    with pytest.raises(ValueError, match="artifact SHA"):
        store.publish_successor(
            _artifact(tmp_path),
            expected_current_sha256=first["artifact_bytes_sha256"],
            reason="artifact SHA must not be a CAS token",
            run_id="strict-invalid-cas",
            identity=_identity(),
        )

    assert first["current_path"].read_bytes() == current_before


def test_strict_successor_stale_cas_does_not_create_evidence(
    tmp_path: Path,
) -> None:
    _materialize_pools(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    first = store.publish(_artifact(tmp_path), run_id="strict-old", identity=_identity())
    current_before = first["current_path"].read_bytes()
    _append_research_pool(tmp_path)

    with pytest.raises(ValueError, match="current raw SHA"):
        store.publish_successor(
            _artifact(tmp_path),
            expected_current_sha256="0" * 64,
            reason="stale CAS must not publish",
            run_id="strict-stale",
            identity=_identity(),
        )

    assert first["current_path"].read_bytes() == current_before
    assert not (tmp_path / "supersessions").exists()
    assert not (tmp_path / "runs" / TRADE_DATE / "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V3" / "strict-stale").exists()


def test_strict_successor_does_not_treat_same_rows_raw_refresh_as_append(
    tmp_path: Path,
) -> None:
    _materialize_pools(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    first = store.publish(_artifact(tmp_path), run_id="strict-old", identity=_identity())
    current_before = first["current_path"].read_bytes()
    expected = hashlib.sha256(current_before).hexdigest()
    _refresh_research_metadata_without_rows(tmp_path)

    with pytest.raises(ValueError, match="append"):
        store.publish_successor(
            _artifact(tmp_path),
            expected_current_sha256=expected,
            reason="same-rows raw refresh must fail",
            run_id="strict-same-rows",
            identity=_identity(),
        )

    assert first["current_path"].read_bytes() == current_before
    assert not (tmp_path / "supersessions").exists()


def test_strict_successor_identity_change_fails_before_current_cas(
    tmp_path: Path,
) -> None:
    _materialize_pools(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    first = store.publish(_artifact(tmp_path), run_id="strict-old", identity=_identity())
    current_before = first["current_path"].read_bytes()
    _append_research_pool(tmp_path)
    changed_identity = EvidenceIdentity(
        owner_id="V3_5_STAGE_CENTER",
        producer_id="ops.materialize_stage_acquisition_universe",
        release_id="different-release",
        lane_id="A_SHARE_STAGE_ACQUISITION",
    )

    with pytest.raises(ValueError, match="identity|current cannot be confirmed"):
        store.publish_successor(
            _artifact(tmp_path),
            expected_current_sha256=hashlib.sha256(current_before).hexdigest(),
            reason="identity change must fail",
            run_id="strict-identity-change",
            identity=changed_identity,
        )

    assert first["current_path"].read_bytes() == current_before
    assert not (tmp_path / "supersessions").exists()


def test_strict_successor_payload_identity_cannot_be_overwritten(
    tmp_path: Path,
) -> None:
    _materialize_pools(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    first = store.publish(_artifact(tmp_path), run_id="strict-old", identity=_identity())
    current_before = first["current_path"].read_bytes()
    expected = hashlib.sha256(current_before).hexdigest()
    _append_research_pool(tmp_path)
    successor = _artifact(tmp_path)
    successor["release_id"] = "forged-release"

    with pytest.raises(ValueError, match="identity"):
        store.publish_successor(
            successor,
            expected_current_sha256=expected,
            reason="payload identity must fail",
            run_id="strict-forged-identity",
            identity=_identity(),
        )

    assert first["current_path"].read_bytes() == current_before
    assert not (tmp_path / "supersessions").exists()


def test_strict_successor_payload_role_cannot_be_overwritten(
    tmp_path: Path,
) -> None:
    _materialize_pools(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    first = store.publish(_artifact(tmp_path), run_id="strict-old", identity=_identity())
    current_before = first["current_path"].read_bytes()
    expected = hashlib.sha256(current_before).hexdigest()
    _append_research_pool(tmp_path)
    successor = _artifact(tmp_path)
    successor["artifact_role"] = "FORGED_ROLE"

    with pytest.raises(ValueError, match="role"):
        store.publish_successor(
            successor,
            expected_current_sha256=expected,
            reason="payload role must fail",
            run_id="strict-forged-role",
            identity=_identity(),
        )

    assert first["current_path"].read_bytes() == current_before
    assert not (tmp_path / "supersessions").exists()


def test_strict_successor_missing_physical_pool_does_not_advance_current(
    tmp_path: Path,
) -> None:
    _materialize_pools(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    first = store.publish(_artifact(tmp_path), run_id="strict-old", identity=_identity())
    _append_research_pool(tmp_path)
    successor = _artifact(tmp_path)
    current_before = first["current_path"].read_bytes()
    missing_pool = tmp_path / "preselection_pools" / TRADE_DATE / "a_d1_premarket_pool.json"
    missing_pool.unlink()

    with pytest.raises(ValueError, match="strict physical snapshot|cannot be confirmed"):
        store.publish_successor(
            successor,
            expected_current_sha256=hashlib.sha256(current_before).hexdigest(),
            reason="missing source pool must fail closed",
            run_id="strict-missing-pool",
            identity=_identity(),
        )

    assert first["current_path"].read_bytes() == current_before


def test_strict_current_verifier_checks_successor_lineage_fields(
    tmp_path: Path,
) -> None:
    _materialize_pools(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    first = store.publish(_artifact(tmp_path), run_id="strict-old", identity=_identity())
    expected = hashlib.sha256(first["current_path"].read_bytes()).hexdigest()
    _append_research_pool(tmp_path)
    store.publish_successor(
        _artifact(tmp_path),
        expected_current_sha256=expected,
        reason="lineage verifier test",
        run_id="strict-new",
        identity=_identity(),
    )
    current_path = first["current_path"]
    current = json.loads(current_path.read_bytes())
    current["previous_current_bytes_sha256"] = "0" * 64
    current_path.write_bytes(
        json.dumps(
            current, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    )

    with pytest.raises(ValueError, match="current binding|predecessor"):
        store.read_strict_verified(TRADE_DATE, identity=_identity())


def test_strict_current_verifier_rejects_tampered_supersession_reason(
    tmp_path: Path,
) -> None:
    _materialize_pools(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    first = store.publish(_artifact(tmp_path), run_id="strict-old", identity=_identity())
    expected = hashlib.sha256(first["current_path"].read_bytes()).hexdigest()
    _append_research_pool(tmp_path)
    result = store.publish_successor(
        _artifact(tmp_path),
        expected_current_sha256=expected,
        reason="canonical reason",
        run_id="strict-new",
        identity=_identity(),
    )
    receipt_path = result["supersession_receipt_path"]
    receipt = json.loads(receipt_path.read_bytes())
    receipt["reason"] = "tampered reason"
    receipt_path.write_bytes(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )

    with pytest.raises(StrictCommitError, match="supersession receipt"):
        store.read_strict_verified(TRADE_DATE, identity=_identity())


@pytest.mark.parametrize(
    "tamper",
    (
        "evolution",
        "successor_run_id",
        "target_current_relative",
        "successor_current_relative",
        "successor_artifact",
        "predecessor_run_id",
    ),
)
def test_strict_current_verifier_rejects_any_supersession_receipt_field_tamper(
    tmp_path: Path, tamper: str
) -> None:
    _materialize_pools(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    first = store.publish(_artifact(tmp_path), run_id="strict-old", identity=_identity())
    expected = hashlib.sha256(first["current_path"].read_bytes()).hexdigest()
    _append_research_pool(tmp_path)
    result = store.publish_successor(
        _artifact(tmp_path),
        expected_current_sha256=expected,
        reason="all receipt fields are committed",
        run_id="strict-new",
        identity=_identity(),
    )
    receipt_path = result["supersession_receipt_path"]
    receipt = json.loads(receipt_path.read_bytes())
    if tamper == "evolution":
        receipt["evolution"] = "FORGED_EVOLUTION"
    elif tamper == "successor_run_id":
        receipt["successor_run_id"] = "forged-successor"
    elif tamper == "target_current_relative":
        receipt["target_current_relative"] = "current/forged.json"
    elif tamper == "successor_current_relative":
        receipt["successor_current_relative"] = "current/forged.json"
    elif tamper == "successor_artifact":
        receipt["successor"]["artifact_canonical_sha256"] = "f" * 64
    else:
        receipt["predecessor"]["run_id"] = "forged-predecessor"
    receipt_path.write_bytes(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )

    with pytest.raises(StrictCommitError, match="supersession receipt"):
        store.read_strict_verified(TRADE_DATE, identity=_identity())


def test_strict_successor_retry_recovers_committed_orphan_before_new_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _materialize_pools(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    first = store.publish(_artifact(tmp_path), run_id="strict-old", identity=_identity())
    predecessor_bytes = first["current_path"].read_bytes()
    expected = hashlib.sha256(predecessor_bytes).hexdigest()
    _append_research_pool(tmp_path)
    successor = _artifact(tmp_path)

    original_create = SecureEvidenceRoot.create_immutable_bytes

    def fail_before_supersession(
        secure: SecureEvidenceRoot, relative: str, data: bytes
    ) -> str:
        if relative.startswith("supersessions/"):
            raise RuntimeError("simulated crash before supersession receipt")
        return original_create(secure, relative, data)

    monkeypatch.setattr(SecureEvidenceRoot, "create_immutable_bytes", fail_before_supersession)
    with pytest.raises(RuntimeError, match="before supersession"):
        store.publish_successor(
            successor,
            expected_current_sha256=expected,
            reason="recover committed orphan",
            run_id="strict-crashed",
            identity=_identity(),
        )
    monkeypatch.undo()

    orphan_dir = (
        tmp_path
        / "runs"
        / TRADE_DATE
        / "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V3"
        / "strict-crashed"
    )
    assert (orphan_dir / "commit.json").is_file()
    assert first["current_path"].read_bytes() == predecessor_bytes

    recovered = store.publish_successor(
        successor,
        expected_current_sha256=expected,
        reason="recover committed orphan",
        run_id="strict-retry-different-run",
        identity=_identity(),
    )

    assert recovered["run_id"] == "strict-crashed"
    assert recovered["idempotent"] is True
    current = store.read_strict_verified(TRADE_DATE, identity=_identity())
    assert current["run_id"] == "strict-crashed"
    assert not (
        tmp_path
        / "runs"
        / TRADE_DATE
        / "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V3"
        / "strict-retry-different-run"
    ).exists()


def test_strict_successor_retry_rejects_multiple_matching_committed_orphans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _materialize_pools(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    first = store.publish(_artifact(tmp_path), run_id="strict-old", identity=_identity())
    predecessor_bytes = first["current_path"].read_bytes()
    expected = hashlib.sha256(predecessor_bytes).hexdigest()
    _append_research_pool(tmp_path)
    successor = _artifact(tmp_path)

    original_create = SecureEvidenceRoot.create_immutable_bytes

    def fail_before_supersession(
        secure: SecureEvidenceRoot, relative: str, data: bytes
    ) -> str:
        if relative.startswith("supersessions/"):
            raise RuntimeError("simulated crash before supersession receipt")
        return original_create(secure, relative, data)

    # Construct two committed run orphans at the same crash boundary.  The
    # recovery hook is disabled only while creating this adversarial fixture;
    # normal retry logic is restored for the assertion below.
    monkeypatch.setattr(
        StageAcquisitionUniverseCommit,
        "_recover_committed_successor_orphan",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(SecureEvidenceRoot, "create_immutable_bytes", fail_before_supersession)
    for run_id in ("strict-crashed-a", "strict-crashed-b"):
        with pytest.raises(RuntimeError, match="before supersession"):
            store.publish_successor(
                successor,
                expected_current_sha256=expected,
                reason="multiple orphan guard",
                run_id=run_id,
                identity=_identity(),
            )
    monkeypatch.undo()

    with pytest.raises(StrictCommitError, match="multiple strict successor"):
        store.publish_successor(
            successor,
            expected_current_sha256=expected,
            reason="multiple orphan guard",
            run_id="strict-retry-after-ambiguity",
            identity=_identity(),
        )

    assert first["current_path"].read_bytes() == predecessor_bytes
    assert not (
        tmp_path
        / "supersessions"
        / TRADE_DATE
        / "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V3"
    ).exists()


def test_strict_retry_rejects_forged_successor_current_before_cas(
    tmp_path: Path,
) -> None:
    _materialize_pools(tmp_path)
    store = StageAcquisitionUniverseStore(tmp_path)
    first = store.publish(_artifact(tmp_path), run_id="strict-old", identity=_identity())
    predecessor_bytes = first["current_path"].read_bytes()
    expected = hashlib.sha256(predecessor_bytes).hexdigest()
    _append_research_pool(tmp_path)
    successor = _artifact(tmp_path)
    result = store.publish_successor(
        successor,
        expected_current_sha256=expected,
        reason="forged successor current test",
        run_id="strict-new",
        identity=_identity(),
    )

    receipt_path = result["supersession_receipt_path"]
    receipt = json.loads(receipt_path.read_bytes())
    receipt["successor_current"] = {"run_id": "forged"}
    receipt["successor_current_bytes_sha256"] = hashlib.sha256(
        json.dumps(
            receipt["successor_current"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    receipt_path.write_bytes(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    first["current_path"].write_bytes(predecessor_bytes)

    with pytest.raises(ValueError, match="successor current"):
        store.publish_successor(
            successor,
            expected_current_sha256=expected,
            reason="forged successor current test",
            run_id="different-retry-run",
            identity=_identity(),
        )

    assert first["current_path"].read_bytes() == predecessor_bytes
