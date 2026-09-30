from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from domains.preselection_materializer import build_expected_missing_pool
from infrastructure import preselection_pool_store as preselection_pool_store_module
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.scope_gate import (
    GateConfigurationError,
    PERMIT_SCHEMA,
    StoreGateContext,
    canonical_bytes,
)


TRADE_DATE = "20260918"
POOL_ID = "a_share_research_recommendation_pool"


def _placeholder() -> dict:
    return build_expected_missing_pool(
        TRADE_DATE,
        pool_id=POOL_ID,
        display_name="A股研报推荐股票池",
        market="A",
        reason="FIXTURE_EXPECTED_MISSING",
    )


def _verified_replacement() -> dict:
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": TRADE_DATE,
        "pool_id": POOL_ID,
        "display_name": "A股研报推荐股票池",
        "market": "A",
        "status": "RESEARCH_RECOMMENDATION_POOL_READY",
        "producer_id": "v3_5_hourly_research_window_v1",
        "source_role": "VERIFIED_HOURLY_RESEARCH",
        "source_path": f"fixture/{TRADE_DATE}/{POOL_ID}.json",
        "source_sha256": hashlib.sha256(b"verified-replacement").hexdigest(),
        "rows": [{
            "symbol": "A.000001",
            "market": "A",
            "pool_id": POOL_ID,
            "pool_rank": 1,
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }],
        "cannot_confirm": ["RESEARCH_ONLY_NO_BUY_GATE"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _valid_gate_context(
    root: Path, control_dir: Path, source_root: Path
) -> StoreGateContext:
    root.mkdir(parents=True)
    control_dir.mkdir(parents=True)
    source_root.mkdir(parents=True)
    keys = [{
        "business_key": "fixture:gate-transition",
        "trade_date": TRADE_DATE,
        "pool_id": POOL_ID,
    }]
    permit = {
        "schema_version": PERMIT_SCHEMA,
        "decision_id": "fixture-gate-transition",
        "owner_id": "fixture-owner",
        "source_release_sha256": "c" * 64,
        "target_release_sha256": "b" * 64,
        "source_root": str(source_root),
        "target_root": str(root),
        "keys": keys,
        "business_key_set_sha256": hashlib.sha256(canonical_bytes(keys)).hexdigest(),
    }
    permit_bytes = canonical_bytes(permit)
    (control_dir / "permit.json").write_bytes(permit_bytes)
    return StoreGateContext(
        control_dir=control_dir,
        expected_permit_sha256=hashlib.sha256(permit_bytes).hexdigest(),
        expected_owner_id="fixture-owner",
        expected_release_sha256="b" * 64,
        expected_root=root,
    )


def _trio_bytes(root: Path) -> dict[str, bytes]:
    date_root = root / "preselection_pools" / TRADE_DATE
    paths = {
        "artifact": date_root / f"{POOL_ID}.json",
        "receipt": date_root / "receipts" / f"{POOL_ID}.json",
        "manifest": date_root / "manifest.json",
    }
    return {name: path.read_bytes() for name, path in paths.items()}


def _root_file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _stored_placeholder(root: Path) -> tuple[PreselectionPoolStore, dict]:
    legacy = PreselectionPoolStore(root)
    placeholder = _placeholder()
    publication = legacy.materialize(placeholder)
    return legacy, publication


def test_required_context_denies_materialize_without_changing_pool_trio(tmp_path: Path) -> None:
    root = tmp_path / "data"
    _stored_placeholder(root)
    before = _root_file_bytes(root)

    guarded = PreselectionPoolStore(root, require_write_gate_context=True)
    with pytest.raises(GateConfigurationError, match="required write-gate context"):
        guarded.materialize(_verified_replacement())

    assert _root_file_bytes(root) == before


def test_required_context_denies_fresh_root_materialize_without_creating_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "fresh-data"
    guarded = PreselectionPoolStore(root, require_write_gate_context=True)

    with pytest.raises(GateConfigurationError, match="required write-gate context"):
        guarded.materialize(_placeholder())

    assert not root.exists()


def test_required_context_is_rechecked_inside_existing_lock(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "data"
    _stored_placeholder(root)
    before = _root_file_bytes(root)
    guarded = PreselectionPoolStore(
        root,
        write_gate_context=StoreGateContext(
            control_dir=tmp_path / "fixture-control",
            expected_permit_sha256="a" * 64,
            expected_owner_id="fixture-owner",
            expected_release_sha256="b" * 64,
            expected_root=root,
        ),
        require_write_gate_context=True,
    )
    lock_path = root / ".import.lock"
    gate_checks = 0

    def allow_preflight_then_deny_locked(_context, **_kwargs) -> None:
        nonlocal gate_checks
        gate_checks += 1
        if gate_checks == 1:
            assert not lock_path.exists()
            return
        assert lock_path.exists()
        raise GateConfigurationError("fixture gate changed before locked recheck")

    monkeypatch.setattr(
        preselection_pool_store_module,
        "assert_write_allowed",
        allow_preflight_then_deny_locked,
    )

    with pytest.raises(GateConfigurationError, match="locked recheck"):
        guarded.materialize(_verified_replacement())

    assert gate_checks == 2
    assert not lock_path.exists()
    assert _root_file_bytes(root) == before


def test_required_context_denies_fresh_root_gate_setter_without_creating_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "fresh-gate-store"
    guarded = PreselectionPoolStore(root, require_write_gate_context=True)

    with pytest.raises(GateConfigurationError):
        guarded.set_write_gate(expected_revision=0, state="FENCED")

    assert not root.exists()


@pytest.mark.parametrize("invalid_context", ["wrong_type", "unavailable_control"])
def test_required_context_denies_invalid_fresh_root_gate_setter_without_writes(
    tmp_path: Path, invalid_context: str
) -> None:
    root = tmp_path / f"invalid-{invalid_context}-store"
    if invalid_context == "wrong_type":
        context = object()
        control_path = None
    else:
        control_path = tmp_path / "missing-control"
        context = StoreGateContext(
            control_dir=control_path,
            expected_permit_sha256="a" * 64,
            expected_owner_id="fixture-owner",
            expected_release_sha256="b" * 64,
            expected_root=root,
        )
    guarded = PreselectionPoolStore(
        root,
        write_gate_context=context,  # type: ignore[arg-type]
        require_write_gate_context=True,
    )

    with pytest.raises(GateConfigurationError):
        guarded.set_write_gate(expected_revision=0, state="FENCED")

    assert not root.exists()
    if control_path is not None:
        assert not control_path.exists()


def test_required_context_denies_missing_permit_before_gate_setter_lock_sidecars(
    tmp_path: Path,
) -> None:
    root = tmp_path / "existing-empty-store"
    root.mkdir()
    control_dir = tmp_path / "empty-control"
    control_dir.mkdir()
    context = StoreGateContext(
        control_dir=control_dir,
        expected_permit_sha256="a" * 64,
        expected_owner_id="fixture-owner",
        expected_release_sha256="b" * 64,
        expected_root=root,
    )
    guarded = PreselectionPoolStore(
        root,
        write_gate_context=context,
        require_write_gate_context=True,
    )
    files_before = _root_file_bytes(root)

    with pytest.raises(GateConfigurationError, match="missing control file: permit.json"):
        guarded.set_write_gate(expected_revision=0, state="FENCED")

    assert _root_file_bytes(root) == files_before
    assert not (root / ".import.lock").exists()


def test_required_context_gate_setter_can_fence_and_reopen_with_valid_permit(
    tmp_path: Path,
) -> None:
    root = tmp_path / "existing-gate-store"
    context = _valid_gate_context(
        root,
        tmp_path / "control",
        tmp_path / "source-root",
    )
    guarded = PreselectionPoolStore(
        root,
        write_gate_context=context,
        require_write_gate_context=True,
    )

    fenced = guarded.set_write_gate(expected_revision=0, state="FENCED")
    reopened = guarded.set_write_gate(expected_revision=1, state="OPEN")

    assert fenced["state"] == "FENCED"
    assert fenced["revision"] == 1
    assert reopened["state"] == "OPEN"
    assert reopened["revision"] == 2


def test_legacy_default_gate_setter_keeps_existing_missing_context_error(
    tmp_path: Path,
) -> None:
    legacy = PreselectionPoolStore(tmp_path / "legacy-gate-store")

    with pytest.raises(
        GateConfigurationError,
        match="write-gate context is required to change gate state",
    ):
        legacy.set_write_gate(expected_revision=0, state="FENCED")


@pytest.mark.parametrize("operation", ["recover", "rollback"])
def test_required_context_denies_fresh_root_recovery_without_lock_sidecars(
    tmp_path: Path, operation: str
) -> None:
    root = tmp_path / f"fresh-{operation}"
    guarded = PreselectionPoolStore(root, require_write_gate_context=True)

    with pytest.raises(GateConfigurationError, match="required write-gate context"):
        if operation == "recover":
            guarded.recover_expected_missing(
                _verified_replacement(), expected_old_sha256="a" * 64
            )
        else:
            guarded.rollback_recovery(
                TRADE_DATE, POOL_ID, expected_current_sha256="b" * 64
            )

    assert not root.exists()


def test_required_context_denies_expected_missing_recovery_without_changing_trio(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    _legacy, publication = _stored_placeholder(root)
    before = _root_file_bytes(root)
    guarded = PreselectionPoolStore(root, require_write_gate_context=True)

    with pytest.raises(GateConfigurationError, match="required write-gate context"):
        guarded.recover_expected_missing(
            _verified_replacement(), expected_old_sha256=publication["sha256"]
        )

    assert _root_file_bytes(root) == before


def test_required_context_denies_rollback_without_changing_pool_trio(tmp_path: Path) -> None:
    root = tmp_path / "data"
    legacy, publication = _stored_placeholder(root)
    recovered = legacy.recover_expected_missing(
        _verified_replacement(), expected_old_sha256=publication["sha256"]
    )
    before = _root_file_bytes(root)
    guarded = PreselectionPoolStore(root, require_write_gate_context=True)

    with pytest.raises(GateConfigurationError, match="required write-gate context"):
        guarded.rollback_recovery(
            TRADE_DATE, POOL_ID, expected_current_sha256=recovered["sha256"]
        )

    assert _root_file_bytes(root) == before


def test_required_context_denies_pending_read_recovery_before_any_trio_write(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    legacy, publication = _stored_placeholder(root)
    replacement = _verified_replacement()
    legacy.recover_expected_missing(
        replacement, expected_old_sha256=publication["sha256"]
    )
    snapshot = legacy._read_pool_snapshot_unlocked(TRADE_DATE, POOL_ID)
    pending_relative = legacy._pending_relative(pool_id=POOL_ID, trade_date=TRADE_DATE)
    pending = legacy._pending_commit(
        snapshot,
        payload=replacement,
        receipt=snapshot["receipt"],
        manifest=snapshot["manifest"],
    )
    legacy._write(pending_relative, pending)
    pending_path = root / pending_relative
    files_before = _root_file_bytes(root)
    guarded = PreselectionPoolStore(root, require_write_gate_context=True)

    with pytest.raises(GateConfigurationError, match="required write-gate context"):
        guarded.read_pool(TRADE_DATE, POOL_ID)

    assert _root_file_bytes(root) == files_before


@pytest.mark.parametrize("reader", ["read_pool", "read_pool_snapshot", "read_all"])
def test_required_context_denies_pending_read_recovery_before_lock_sidecars(
    tmp_path: Path, reader: str
) -> None:
    root = tmp_path / "pending-only-root"
    pending = root / "preselection_pending_commits" / TRADE_DATE / f"{POOL_ID}.json"
    pending.parent.mkdir(parents=True)
    pending.write_bytes(b"{}\n")
    files_before = _root_file_bytes(root)
    guarded = PreselectionPoolStore(root, require_write_gate_context=True)

    with pytest.raises(GateConfigurationError, match="required write-gate context"):
        if reader == "read_all":
            guarded.read_all(TRADE_DATE)
        else:
            getattr(guarded, reader)(TRADE_DATE, POOL_ID)

    assert _root_file_bytes(root) == files_before


def test_invalid_required_control_path_fails_closed_before_materialize(tmp_path: Path) -> None:
    root = tmp_path / "data"
    missing_control = tmp_path / "unavailable-control"
    context = StoreGateContext(
        control_dir=missing_control,
        expected_permit_sha256="a" * 64,
        expected_owner_id="fixture-owner",
        expected_release_sha256="b" * 64,
        expected_root=root,
    )
    guarded = PreselectionPoolStore(
        root,
        write_gate_context=context,
        require_write_gate_context=True,
    )

    with pytest.raises(GateConfigurationError, match="unavailable control directory"):
        guarded.materialize(_verified_replacement())

    assert not root.exists()
    assert not missing_control.exists()


def test_required_context_does_not_block_read_when_no_recovery_is_pending(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    _stored_placeholder(root)
    guarded = PreselectionPoolStore(root, require_write_gate_context=True)

    assert guarded.read_pool(TRADE_DATE, POOL_ID) == _placeholder()


def test_legacy_default_store_keeps_existing_materialize_and_read_behavior(
    tmp_path: Path,
) -> None:
    root = tmp_path / "legacy-data"
    legacy = PreselectionPoolStore(root)
    payload = _placeholder()

    publication = legacy.materialize(payload)

    assert publication["sha256"]
    assert legacy.read_pool(TRADE_DATE, POOL_ID) == payload
